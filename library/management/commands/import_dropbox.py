from django.core.management.base import BaseCommand
from library.models import Book
import dropbox
import os

class Command(BaseCommand):
    help = 'Imports books from a specific Dropbox folder'

    def add_arguments(self, parser):
        parser.add_argument('folder_path', type=str, help='Path to folder in Dropbox (e.g., /MyBooks)')

    def handle(self, *args, **options):
        folder_path = options['folder_path']
        dbx_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
        
        if not dbx_token:
            self.stdout.write(self.style.ERROR('DROPBOX_ACCESS_TOKEN not found in environment.'))
            return

        dbx = dropbox.Dropbox(dbx_token)

        try:
            self.stdout.write(f"Scanning {folder_path}...")
            # Recursive listing could be done, but simple list_folder for now
            result = dbx.files_list_folder(folder_path, recursive=True)
            
            def process_entries(entries):
                for entry in entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        self.process_file(dbx, entry)

            process_entries(result.entries)

            while result.has_more:
                result = dbx.files_list_folder_continue(result.cursor)
                process_entries(result.entries)
                
            self.stdout.write(self.style.SUCCESS('Import complete!'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))

    def process_file(self, dbx, entry):
        # Check if book exists
        title = entry.name.replace('.pdf', '').replace('.epub', '').replace('_', ' ').strip()
        if Book.objects.filter(title__iexact=title).exists():
            self.stdout.write(f"Skipping existing book: {title}")
            return

        # Create Shared Link
        link = ""
        try:
            # First try to create (might fail if exists)
            link_meta = dbx.sharing_create_shared_link_with_settings(entry.path_lower)
            link = link_meta.url
        except dropbox.exceptions.ApiError as e:
            # If already exists, list it
            if e.error.is_shared_link_already_exists():
                links = dbx.sharing_list_shared_links(path=entry.path_lower).links
                if links:
                    link = links[0].url
            else:
                self.stdout.write(self.style.ERROR(f"Error getting link for {title}: {e}"))
                return # Skip if we can't get a link

        if link:
            Book.objects.create(
                title=title,
                type='SC',
                author='Unknown Import',
                owner='FAYM',
                location=link,
                availability='Available',
                keywords=''
            )
            self.stdout.write(self.style.SUCCESS(f"Imported: {title}"))
