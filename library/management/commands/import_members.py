from django.core.management.base import BaseCommand
from library.models import Member
import csv
import datetime

class Command(BaseCommand):
    help = 'Imports members from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        
        self.stdout.write(f"Reading {csv_file_path}...")
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    # Map CSV columns to Model fields
                    # Expected CSV headers: FIRSTNAME, SURNAME, OTHERNAMES, DATEOFBIRTH, EMAIL, MOBILENUMBER, RESIDENCE, LANDMARK
                    
                    email = row.get('EMAIL', '').strip()
                    if not email:
                        continue # Skip empty rows
                        
                    dob = None
                    dob_str = row.get('DATEOFBIRTH', '').strip()
                    if dob_str:
                        try:
                            dob = datetime.datetime.strptime(dob_str, '%Y-%m-%d').date()
                        except ValueError:
                            pass # Handle other formats or skip
                    
                    obj, created = Member.objects.get_or_create(
                        email=email,
                        defaults={
                            'firstname': row.get('FIRSTNAME', ''),
                            'surname': row.get('SURNAME', ''),
                            'othernames': row.get('OTHERNAMES', ''),
                            'date_of_birth': dob,
                            'mobile_number': row.get('MOBILENUMBER', ''),
                            'residence': row.get('RESIDENCE', ''),
                            'landmark': row.get('LANDMARK', ''),
                        }
                    )
                    
                    if created:
                        count += 1
                        
                self.stdout.write(self.style.SUCCESS(f'Successfully imported {count} new members.'))
        except FileNotFoundError:
             self.stdout.write(self.style.ERROR('File not found.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
