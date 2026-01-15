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
import threading
import datetime
import uuid
import requests
from django.core.mail import send_mail

from django.db.models import Count
from collections import Counter

def index(request):
    """Main landing page with search and dynamic categories."""
    books = Book.objects.all().order_by('-book_id')[:20]
    
    # Aggregate all keywords
    all_books = Book.objects.values_list('keywords', flat=True)
    keyword_counter = Counter()
    
    for k_str in all_books:
        if k_str:
            # Split by comma, strip whitespace, and normalize
            parts = [k.strip().title() for k in k_str.split(',') if k.strip()]
            keyword_counter.update(parts)
            
    # Get top 15 most common categories
    categories = [k for k, v in keyword_counter.most_common(15)]
    
    return render(request, 'library/index.html', {'books': books, 'categories': categories})

def send_sms_wigal(phone, message):
    """Send SMS using Wigal API."""
    api_key = settings.WIGAL_API_KEY
    username = settings.WIGAL_USERNAME
    sender_id = settings.WIGAL_SENDER_ID
    
    if not api_key or not username:
        print("WIGAL credentials not set. SMS skipped.")
        return

    # Use the v2 endpoint which is common for Wigal
    url = 'https://logon.wigal.com.gh/api/v2/sendmsg'
    
    # Headers typically require Basic Auth or separate keys depending on version
    # Based on search: API-KEY and USERNAME in headers is a common pattern
    headers = {
        'Content-Type': 'application/json',
        'api_key': api_key, # Try header based auth first
        'username': username
    }
    
    # Payload
    payload = {
        "sender_id": sender_id,
        "phone": phone,
        "message": message
    }
    
    try:
        # Some versions pass credentials in payload, let's try standard POST first
        response = requests.post(url, json=payload, headers=headers)
        
        # Fallback: If 401, try query params or different payload structure if needed
        # But for now, we follow the common header pattern
    except Exception as e:
        print(f"SMS Failed: {e}")

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
    """Dashboard for running bulk import commands."""
    if not request.user.is_staff:
        # redirect or 403
        return redirect('index')

    if request.method == 'POST':
        if 'sync_dropbox' in request.POST:
            folder = request.POST.get('dropbox_path')
            
            def run_sync():
                # Run the command with a dummy output or capture it if we implemented logging
                try:
                    call_command('import_dropbox', folder)
                except Exception as e:
                    print(f"Background Sync Error: {e}")

            # Start in background thread
            thread = threading.Thread(target=run_sync)
            thread.start()
            
            messages.success(request, f"Dropbox Sync started in background for '{folder}'. This may take a few minutes. Check the 'Books' list periodically.")
            return redirect('bulk_import')

        elif 'import_members' in request.POST:
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

        elif 'update_metadata' in request.POST:
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, "Please upload a CSV file.")
            else:
                try:
                    decoded_file = csv_file.read().decode('utf-8').splitlines()
                    reader = csv.DictReader(decoded_file)
                    updated = 0
                    created = 0
                    skipped_no_link = 0
                    
                    for row in reader:
                        title = row.get('Title', '').strip()
                        if not title: continue
                        
                        share_link = row.get('Shareable Link', '').strip()
                        cover_url = row.get('Cover URL', '').strip()
                        author = row.get('Author', '').strip()
                        keywords = row.get('Keywords', '').strip()
                        
                        # 1. Try to find existing book
                        books = Book.objects.filter(title__iexact=title)
                        if not books.exists():
                             books = Book.objects.filter(title__icontains=title)
                             
                        # 2. If no book found AND we have a link, CREATE IT
                        if not books.exists():
                            if share_link:
                                try:
                                    Book.objects.create(
                                        title=title,
                                        author=author or 'Unknown',
                                        keywords=keywords,
                                        location=share_link,
                                        cover_url=cover_url,
                                        type='SC',
                                        owner='FAYM',
                                        availability='Available'
                                    )
                                    created += 1
                                    continue
                                except: pass
                            else:
                                skipped_no_link += 1
                                continue
                            
                        # 3. Update existing books
                        for book in books:
                            changed = False
                            if author: 
                                book.author = author
                                changed = True
                            if keywords: 
                                book.keywords = keywords
                                changed = True
                            if share_link and not book.location:
                                book.location = share_link
                                changed = True
                            if cover_url and not book.cover_url:
                                book.cover_url = cover_url
                                changed = True
                                
                            if changed:
                                book.save()
                                updated += 1
                                
                    msg = f"Process Complete. Created: {created}, Updated: {updated}."
                    if skipped_no_link > 0:
                        msg += f" Skipped {skipped_no_link} new books (Missing 'Shareable Link')."
                    messages.success(request, msg)
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
            messages.error(request, "Access Denied: You are not a registered member of the ministry.")
            return redirect('index')
            
        # Create Request
        req = BookRequest.objects.create(
            full_name=f"{member.firstname} {member.surname}",
            email=member.email,
            book=book,
            request_status='Valid',
            approval_status='Pending'
        )
        
        # === SCENARIO 1: SOFT COPY (Auto-Approve) ===
        if book.type == 'SC':
            req.approval_status = 'Approved'
            req.save()
            
            # Message
            sms_msg = f"Request Received. Token: {req.token}. Link: {book.location}"
            email_body = f"Hello {member.firstname},\n\nYour request for '{book.title}' is approved.\n\nToken: {req.token}\nLink: {book.location}\n\nFAYM Library"
            
            # Send
            threading.Thread(target=send_sms_wigal, args=(member.mobile_number, sms_msg)).start()
            try:
                send_mail(f"Approved: {book.title}", email_body, settings.EMAIL_HOST_USER if hasattr(settings, 'EMAIL_HOST_USER') else 'noreply@faymlib.com', [member.email])
            except: pass
            
        # === SCENARIO 2: HARD COPY (Availability Check) ===
        else:
            # Check if available
            if book.availability != 'Available':
                # This should logically prevent request, but if they get here:
                messages.error(request, f"Book is currently unavailable. Check back later.")
                req.delete() # Undo creation
                return redirect('index')
            
            # Available -> Pending Approval
            sms_msg = f"Request Received. Token: {req.token}. We will contact you shortly."
            email_body = f"Hello {member.firstname},\n\nWe received your request for '{book.title}'.\nToken: {req.token}\n\nWe will contact you shortly for pickup.\n\nFAYM Library"
            
            threading.Thread(target=send_sms_wigal, args=(member.mobile_number, sms_msg)).start()
            try:
                send_mail(f"Received: {book.title}", email_body, settings.EMAIL_HOST_USER if hasattr(settings, 'EMAIL_HOST_USER') else 'noreply@faymlib.com', [member.email])
            except: pass
            
        messages.success(request, f"Request received! Token: {req.token}")
            
        messages.success(request, f"Request received! Token: {req.token}")
        return redirect('index')
        
    return redirect('index')
