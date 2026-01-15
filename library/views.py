from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from .models import Book, Member, BookRequest
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
import io
import csv
import datetime
import uuid

def index(request):
    """Main landing page with search."""
    books = Book.objects.all().order_by('-book_id')[:20] # Show recent
    categories = ["Faith", "Love", "Leadership", "Prayer", "Fiction", "Finance"]
    return render(request, 'library/index.html', {'books': books, 'categories': categories})

def search_books(request):
    """HTMX view for searching books."""
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    
    books = Book.objects.all()
    
    if query:
        books = books.filter(
            Q(title__icontains=query) | 
            Q(author__icontains=query) |
            Q(keywords__icontains=query)
        )
    
    if category:
        books = books.filter(keywords__icontains=category)
        
    context = {'books': books}
    return render(request, 'library/partials/book_list.html', context)

def check_member(request):
    """HTMX/API check if member exists."""
    email_or_phone = request.GET.get('identity', '').strip()
    if not email_or_phone:
        return JsonResponse({'valid': False})
    
    exists = Member.objects.filter(
        Q(email__iexact=email_or_phone) | 
        Q(mobile_number__iexact=email_or_phone)
    ).exists()
    
    return JsonResponse({'valid': exists})

@staff_member_required
def bulk_import(request):
    """Admin-only view for bulk operations."""
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'sync_dropbox':
            # Run the management command logic directly or via call_command
            # Note: call_command output capturing is tricky in views but we'll try basic
            try:
                # We need a folder path. Let's assume root '/' or get from input
                folder = request.POST.get('dropbox_folder', '/')
                output = io.StringIO()
                call_command('import_dropbox', folder, stdout=output)
                messages.success(request, f"Dropbox Sync: {output.getvalue()}")
            except Exception as e:
                messages.error(request, f"Dropbox Sync Error: {e}")
                
        elif action == 'import_members':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, "Please upload a CSV file.")
            else:
                try:
                    # Parse CSV directly here to avoid saving to disk
                    decoded_file = csv_file.read().decode('utf-8').splitlines()
                    reader = csv.DictReader(decoded_file)
                    count = 0
                    for row in reader:
                        email = row.get('EMAIL', '').strip()
                        if not email: continue
                        
                        dob = None
                        if row.get('DATEOFBIRTH'):
                            try:
                                dob = datetime.datetime.strptime(row.get('DATEOFBIRTH'), '%Y-%m-%d').date()
                            except: pass
                            
                        Member.objects.get_or_create(
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
                        count += 1
                    messages.success(request, f"Imported {count} members successfully.")
                except Exception as e:
                    messages.error(request, f"Member Import Error: {e}")

        elif action == 'update_metadata':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, "Please upload a CSV file.")
            else:
                try:
                    decoded_file = csv_file.read().decode('utf-8').splitlines()
                    reader = csv.DictReader(decoded_file)
                    updated = 0
                    for row in reader:
                        title = row.get('Title', '').strip()
                        if not title: continue
                        
                        # Logic from command
                        books = Book.objects.filter(title__icontains=title)
                        for book in books:
                            book.author = row.get('Author', book.author)
                            book.keywords = row.get('Keywords', book.keywords)
                            book.save()
                            updated += 1
                    messages.success(request, f"Updated metadata for {updated} books.")
                except Exception as e:
                    messages.error(request, f"Metadata Update Error: {e}")

        return redirect('bulk_import')

    return render(request, 'library/bulk_import.html')

def submit_request(request):
    if request.method == 'POST':
        book_id = request.POST.get('book_id')
        identity = request.POST.get('identity') # Email or Phone
        full_name = request.POST.get('full_name') # Optional check?
        
        book = get_object_or_404(Book, book_id=book_id)
        
        # Validate Member
        member = Member.objects.filter(
            Q(email__iexact=identity) | 
            Q(mobile_number__iexact=identity)
        ).first()
        
        if not member:
            messages.error(request, "Membership validation failed. Please register first.")
            return redirect('index')
            
        # Create Request
        req = BookRequest.objects.create(
            full_name=f"{member.firstname} {member.surname}",
            email=member.email,
            book=book,
            request_status='Valid', # Since we validated
            approval_status='Pending'
        )
        
        # Automations (SC auto-approve placeholder)
        if book.type == 'SC':
            # Logic to send email would go here
            pass
            
        messages.success(request, f"Request received! Token: {req.token}")
        return redirect('index')
        
    return redirect('index')
