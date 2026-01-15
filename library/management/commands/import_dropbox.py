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
        # Basic check if book exists by title (derived from filename)
        # simplistic assumption: Filename = Title.pdf
        filename = entry.name
        title = filename.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ')
        
        if Book.objects.filter(title__iexact=title).exists():
            self.stdout.write(f"Skipping existing: {title}")
            return

        # Get Share Link
        link = ""
        try:
            # Check existing links
            links = dbx.sharing_list_shared_links(path=entry.path_lower).links
            if links:
                link = links[0].url
            else:
                # Create new
                link_meta = dbx.sharing_create_shared_link_with_settings(entry.path_lower)
                link = link_meta.url
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not link {filename}: {e}"))
            
        if link:
            Book.objects.create(
                title=title,
                author="Unknown Import", # User will have to edit this later
                type='SC',
                keywords="Imported",
                owner="FAYM",
                location=link,
                availability="Available"
            )
            self.stdout.write(self.style.SUCCESS(f"Imported: {title}"))
