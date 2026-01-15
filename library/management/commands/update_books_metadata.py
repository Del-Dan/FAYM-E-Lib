from django.core.management.base import BaseCommand
from library.models import Book
import csv
from django.db.models import Q

class Command(BaseCommand):
    help = 'Updates book metadata (Author, Keywords) from a CSV file matching by Title'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        self.stdout.write(f"Reading {csv_file_path}...")
        
        updated_count = 0
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Expected CSV: Title, Author, Keywords
                    title = row.get('Title', '').strip()
                    if not title:
                        continue
                        
                    # Fuzzy match or exact match? Let's try exact first, then icontains
                    books = Book.objects.filter(title__iexact=title)
                    if not books.exists():
                        # Try partial match (Dropbox filenames might vary slightly)
                        books = Book.objects.filter(title__icontains=title)
                    
                    for book in books:
                        changed = False
                        author = row.get('Author', '').strip()
                        keywords = row.get('Keywords', '').strip()
                        
                        if author and book.author in ['Unknown', 'Unknown Import']:
                            book.author = author
                            changed = True
                        
                        if keywords and not book.keywords:
                            book.keywords = keywords
                            changed = True
                            
                        if changed:
                            book.save()
                            updated_count += 1
                            self.stdout.write(f"Updated: {book.title}")
                            
            self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} books.'))
            
        except FileNotFoundError:
             self.stdout.write(self.style.ERROR('File not found.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
