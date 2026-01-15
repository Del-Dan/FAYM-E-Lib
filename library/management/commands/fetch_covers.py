from django.core.management.base import BaseCommand
from library.models import Book
import requests
import time

class Command(BaseCommand):
    help = 'Fetches book covers from Open Library API'

    def handle(self, *args, **options):
        books = Book.objects.filter(cover_url__isnull=True)
        self.stdout.write(f"checking {books.count()} books for covers...")
        
        updated = 0
        for book in books:
            try:
                # Search by Title + Author (if available)
                query = f"title={book.title}"
                if book.author and book.author not in ['Unknown', 'Unknown Import']:
                    query += f"&author={book.author}"
                
                # Using OpenLibrary Search API
                search_url = f"https://openlibrary.org/search.json?{query}&limit=1"
                response = requests.get(search_url)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('docs'):
                        doc = data['docs'][0]
                        cover_i = doc.get('cover_i')
                        
                        if cover_i:
                            # Construct Cover URL
                            image_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
                            book.cover_url = image_url
                            book.save()
                            updated += 1
                            self.stdout.write(self.style.SUCCESS(f"Found cover for: {book.title}"))
                        else:
                             self.stdout.write(f"No cover found for: {book.title}")
                    else:
                        self.stdout.write(f"No match for: {book.title}")
                
                # Be nice to the API
                time.sleep(0.5)
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error checking {book.title}: {e}"))
                
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} books with covers."))
