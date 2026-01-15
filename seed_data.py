import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'elib_project.settings')
django.setup()

from library.models import Book, Member

def seed():
    print("Seeding data...")
    
    # Create Members
    members = [
        {'firstname': 'John', 'surname': 'Doe', 'email': 'john@example.com', 'mobile': '0240000001'},
        {'firstname': 'Jane', 'surname': 'Smith', 'email': 'jane@example.com', 'mobile': '0240000002'},
    ]
    
    for m in members:
        Member.objects.get_or_create(
            email=m['email'],
            defaults={
                'firstname': m['firstname'],
                'surname': m['surname'],
                'mobile_number': m['mobile'],
                'residence': 'Accra'
            }
        )
    
    # Create Books
    books = [
        {'title': 'The Purpose Driven Life', 'author': 'Rick Warren', 'type': 'HC', 'keywords': 'Purpose, Faith, Life'},
        {'title': 'Atomic Habits', 'author': 'James Clear', 'type': 'SC', 'keywords': 'Habits, Growth, Self-help'},
        {'title': 'Rich Dad Poor Dad', 'author': 'Robert Kiyosaki', 'type': 'HC', 'keywords': 'Finance, Money, Wealth'},
        {'title': 'Mere Christianity', 'author': 'C.S. Lewis', 'type': 'SC', 'keywords': 'Faith, Christianity, Logic'},
        {'title': 'Leadership 101', 'author': 'John Maxwell', 'type': 'HC', 'keywords': 'Leadership, Management'},
    ]
    
    for b in books:
        Book.objects.get_or_create(
            title=b['title'],
            defaults={
                'author': b['author'],
                'type': b['type'],
                'keywords': b['keywords'],
                'availability': 'Available',
                'owner': 'FAYM' if b['type'] == 'SC' else 'Library',
                'location': 'Dropbox Link' if b['type'] == 'SC' else 'Shelf A'
            }
        )
        
    print("Seeding complete.")

if __name__ == '__main__':
    seed()
