from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from .models import Book, Member, BookRequest, OTPRecord
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
import io
import csv
import threading
import datetime
from datetime import timedelta
from django.utils import timezone
import uuid
import requests
from django.core.mail import send_mail
from django.core.paginator import Paginator

from django.db.models import Count
from collections import Counter

def index(request):
    """Main landing page with search and dynamic categories."""
    books = Book.objects.all().order_by('-book_id')
    
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
    
    # Pagination
    paginator = Paginator(books, 20) # Show 20 contacts per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.headers.get('HX-Request'):
        return render(request, 'library/partials/book_list.html', {'books': page_obj})

    return render(request, 'library/index.html', {'books': page_obj, 'categories': categories})

def send_sms_wigal(phone, message):
    """Send SMS using Wigal Frog v3 API."""
    api_key = settings.WIGAL_API_KEY
    username = settings.WIGAL_USERNAME
    sender_id = settings.WIGAL_SENDER_ID
    
    if not api_key or not username:
        print("WIGAL credentials not set. SMS skipped.")
        return

    # User provided working "Frog" API v3 URL
    url = 'https://frogapi.wigal.com.gh/api/v3/sms/send'
    
    # Intelligent Number Formatting
    # 1. Strip all non-digits (keep length checks clean)
    raw_phone = str(phone).strip()
    clean_phone = ''.join(filter(str.isdigit, raw_phone))
    
    # 2. Logic for Ghana Numbers
    if len(clean_phone) == 10 and clean_phone.startswith('0'):
        # e.g. 0554020123 -> 233554020123
        clean_phone = '233' + clean_phone[1:]
    elif len(clean_phone) == 9 and not clean_phone.startswith('0'):
        # e.g. 554020123 -> 233554020123
        clean_phone = '233' + clean_phone
    # else: leave as-is (e.g. already 233... or foreign number)
    
    headers = {
        'Content-Type': 'application/json',
        'API-KEY': api_key,
        'USERNAME': username
    }
    
    # Frog Payload Structure
    # destinations is an array of objects
    payload = {
        "senderid": sender_id,
        "destinations": [
            {
                "destination": clean_phone,
                "msgid": f"FAYM_{uuid.uuid4().hex[:10]}"
            }
        ],
        "message": message,
        "smstype": "text"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        print(f"SMS Response ({response.status_code}): {response.text}") # Debug log
    except Exception as e:
        print(f"SMS Failed: {e}")

def search_books(request):
    """HTMX view for searching books."""
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    filter_type = request.GET.get('filter_type', 'all')
    
    books = Book.objects.all().order_by('-book_id')
    
    if query:
        if filter_type == 'title':
            books = books.filter(title__icontains=query)
        elif filter_type == 'author':
            books = books.filter(author__icontains=query)
        elif filter_type == 'keywords':
             books = books.filter(keywords__icontains=query)
        else:
            books = books.filter(
                Q(title__icontains=query) | 
                Q(author__icontains=query) |
                Q(keywords__icontains=query)
            )
    
    if category:
        books = books.filter(keywords__icontains=category)
        
    if category:
        books = books.filter(keywords__icontains=category)
        
    # Pagination
    paginator = Paginator(books, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    context = {'books': page_obj}
    return render(request, 'library/partials/book_list.html', context)

def suggest_books(request):
    """HTMX view for search suggestions."""
    query = request.GET.get('q', '')
    if len(query) < 2:
        return HttpResponse('')
        
    # Get top 5 matches
    books = Book.objects.filter(title__icontains=query)[:5]
    
    options = ""
    for book in books:
        options += f'<option value="{book.title}"></option>'
    
    return HttpResponse(options)

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
        action = request.POST.get('action')
        
        if action == 'sync_dropbox':
            folder = request.POST.get('dropbox_folder') # Fixed key name from template
            
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
                    print(f"DEBUG: CSV Headers detected: {reader.fieldnames}") # DEBUG
                    updated = 0
                    created = 0
                    skipped_no_link = 0
                    
                    for i, row in enumerate(reader):
                        if i < 3: print(f"DEBUG: Row {i}: {row}") # DEBUG
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

# --- OTP Helper Functions ---
def generate_wigal_otp(phone):
    """Generate OTP Locally and Send via SMS."""
    try:
        # Generate 6-digit code
        import random
        otp_code = str(random.randint(100000, 999999))
        
        # Construct Message
        msg = f"Your FAYM Library OTP is {otp_code}. Valid for 5 minutes."
        
        # Send via existing SMS function
        send_sms_wigal(phone, msg)
        
        return otp_code
    except Exception as e:
        print(f"OTP Gen Error: {e}")
        return None

def verify_wigal_otp(phone, code):
    """Verify OTP using Wigal Frog v3."""
    api_key = settings.WIGAL_API_KEY
    username = settings.WIGAL_USERNAME
    
    url = 'https://frogapi.wigal.com.gh/api/v3/sms/otp/verify'
     
    # Format Phone (Same logic)
    clean_phone = str(phone).strip()
    clean_phone = ''.join(filter(str.isdigit, clean_phone))
    if len(clean_phone) == 10 and clean_phone.startswith('0'):
        clean_phone = '233' + clean_phone[1:]
    elif len(clean_phone) == 9:
        clean_phone = '233' + clean_phone
        
    payload = {
        "number": clean_phone,
        "otpcode": code
    }
    
    headers = {'Content-Type': 'application/json', 'API-KEY': api_key, 'USERNAME': username}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        print(f"OTP Verify Response: {data}")
        # Check status from Wigal response
        return data.get('status') == 'success' # Adjust based on actual response key
    except Exception as e:
        print(f"OTP Verify Error: {e}")
        return False

# --- OTP Views ---

def send_otp(request):
    """HTMX View to trigger OTP sending via EMAIL lookup."""
    identity = request.POST.get('identity', '').strip()
    
    # 1. Lookup by EMAIL explicitly as requested
    member = Member.objects.filter(email__iexact=identity).first()
    
    if not member:
        # Fallback: Try Phone just in case, but prefer Email
        member = Member.objects.filter(mobile_number__iexact=identity).first()
        
    if not member:
        return JsonResponse({'status': 'error', 'message': 'Member email not found in directory.'})
    
    # Generate Code via Wigal
    otp_code = generate_wigal_otp(member.mobile_number)
    
    if otp_code:
        # Store in DB (Temporal Storage as requested)
        # Invalidate previous unverified codes
        OTPRecord.objects.filter(phone_number=member.mobile_number, is_verified=False).delete()
        
        OTPRecord.objects.create(
            phone_number=member.mobile_number,
            otp_code=otp_code,
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        
        # Session storage
        request.session['otp_phone'] = member.mobile_number
        # Mask phone for user feedback
        masked_phone = f"{member.mobile_number[:3]}****{member.mobile_number[-3:]}"
        return JsonResponse({'status': 'sent', 'message': f'OTP sent to registered phone ({masked_phone})'})
    else:
        return JsonResponse({'status': 'error', 'message': 'System error sending OTP.'})

def submit_request(request):
    if request.method == 'POST':
        # --- OTP SECURITY CHECK ---
        is_verified = request.session.get('is_verified')
        session_expiry = request.session.get('session_expiry')
        
        if not is_verified or not session_expiry:
             messages.error(request, "Security Session Expired. Please verify via OTP.")
             return redirect('index')
             
        # Check Expiry
        expiry_dt = datetime.datetime.fromisoformat(session_expiry)
        if timezone.now() > expiry_dt:
             del request.session['is_verified']
             del request.session['session_expiry']
             messages.error(request, "Security Session Expired. Please verify via OTP.")
             return redirect('index')
        # --------------------------

        book_id = request.POST.get('book_id')
        identity = request.POST.get('identity') # This is the Email
        
        book = get_object_or_404(Book, book_id=book_id)
        
        # Validate Member by Email
        member = Member.objects.filter(email__iexact=identity).first()
        
        if not member:
            messages.error(request, "Authentication Error: Member profile not found.")
            return redirect('index')
            
        # --- NEW: Request Limits Check ---
        limit_error = check_request_limits(member, book.type)
        if limit_error:
            messages.error(request, limit_error)
            return redirect('index')
        # ---------------------------------

        # Create Request
        # Note: If HC, model.save() will auto-set Book to 'On Hold'
        req = BookRequest.objects.create(
            member=member,
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
            
            # Professional Message
            sms_msg = f"FAYM Library: Request Approved.\nToken: {req.token}\nAccess your copy here: {book.location}"
            email_body = f"Hello {member.firstname},\n\nYour request for '{book.title}' has been automatically approved.\n\nToken: {req.token}\nAccess Link: {book.location}\n\nHappy Reading!\nFAYM Library"
            
            threading.Thread(target=send_sms_wigal, args=(member.mobile_number, sms_msg)).start()
            try:
                send_mail(f"Access Granted: {book.title}", email_body, settings.EMAIL_HOST_USER if hasattr(settings, 'EMAIL_HOST_USER') else 'noreply@faymlib.com', [member.email])
            except: pass
            
        # === SCENARIO 2: HARD COPY (On Hold Logic) ===
        else:
            # Check availability (Double check, though Request button handles UI)
            # The model save() already set it "On Hold" if it was "Available".
            # If it was already Taken/On Hold by race condition, we should handle that.
            
            if book.availability == 'Taken': 
                 # Race condition caught
                 req.delete()
                 messages.error(request, "Sorry, this book was just taken by someone else.")
                 return redirect('index')

            # Professional Message
            sms_msg = f"FAYM Library: Request Received.\nToken: {req.token}\nWe will contact you shortly regarding pickup."
            email_body = f"Hello {member.firstname},\n\nWe have received your request for '{book.title}'.\nToken: {req.token}\n\nYour request is valid for 5 Hours. We will facilitate pickup shortly.\n\nFAYM Library"
            
            threading.Thread(target=send_sms_wigal, args=(member.mobile_number, sms_msg)).start()
            try:
                send_mail(f"Request Pending: {book.title}", email_body, settings.EMAIL_HOST_USER if hasattr(settings, 'EMAIL_HOST_USER') else 'noreply@faymlib.com', [member.email])
            except: pass
            
        messages.success(request, f"Request Successful! Token: {req.token}")
        return redirect('index')
        
    return redirect('index')

@staff_member_required
def admin_dashboard_view(request):
    """
    Detailed Analytics Dashboard with Auto-Expiry Logic.
    """
    
    # --- AUTO-EXPIRY LOGIC (5 HOURS) ---
    # Check for Pending HC Requests older than 5 hours
    expiry_threshold = timezone.now() - timedelta(hours=5)
    expired_requests = BookRequest.objects.filter(
        approval_status='Pending',
        book__type='HC',
        timestamp__lt=expiry_threshold
    )
    
    count_expired = 0
    if expired_requests.exists():
        for req in expired_requests:
            req.approval_status = 'Expired'
            req.save() # This triggers Book -> 'Available' in model.save()
            count_expired += 1
        print(f"Auto-Expired {count_expired} requests.")
    # -----------------------------------

    # --- FILTERS ---
    month = request.GET.get('month')
    year = request.GET.get('year')
    current_year = datetime.datetime.now().year
    
    # Base Queryset
    qs = BookRequest.objects.all()
    
    if year:
        qs = qs.filter(timestamp__year=year)
    if month:
        qs = qs.filter(timestamp__month=month)
        
    # 1. KPI Counts (Filtered)
    total_requests = qs.count()
    approved_count = qs.filter(approval_status='Approved').count()
    pending_count = qs.filter(approval_status='Pending').count()
    active_members = Member.objects.count() 
    
    # Missed Opportunities (Expired)
    missed_count = qs.filter(approval_status='Expired').count()
    
    # 1b. Lead Time
    valid_approvals = qs.filter(approval_status='Approved', approval_date__isnull=False)
    lead_times = [(r.approval_date - r.timestamp).total_seconds() for r in valid_approvals]
    
    if lead_times:
        avg_seconds = sum(lead_times) / len(lead_times)
        avg_hours = round(avg_seconds / 3600, 1)
        lead_time_display = f"{avg_hours} Hours"
    else:
        lead_time_display = "N/A"

    # 2. Top Books (Flattened Title Context)
    top_books = qs.values('book__title').annotate(count=Count('id')).order_by('-count')[:5]
    # Rename key for template simplicity if needed, but template can use book__title
    
    # 3. Top Members
    top_members = qs.values('full_name').annotate(count=Count('id')).order_by('-count')[:5]

    # 4. Pie Chart Data
    status_counts = qs.values('approval_status').annotate(count=Count('id'))
    pie_labels = [item['approval_status'] for item in status_counts]
    pie_data = [item['count'] for item in status_counts]

    # 5. Line Chart (Requests over time - respect filter or default to 30 days)
    if month or year:
        # If filter active, show daily trend for that period
        chart_qs = qs.order_by('timestamp')
        date_map = defaultdict(int)
        for req in chart_qs:
             d_str = req.timestamp.strftime('%Y-%m-%d')
             date_map[d_str] += 1
        
        # Sort labels
        time_labels = sorted(date_map.keys())
        time_data = [date_map[d] for d in time_labels]
        
    else:
        # Default: Last 30 days
        last_30_days = timezone.now() - timedelta(days=30)
        daily_qs = BookRequest.objects.filter(timestamp__gte=last_30_days).values_list('timestamp', flat=True)
        
        date_map = defaultdict(int)
        for ts in daily_qs:
            date_str = ts.strftime('%Y-%m-%d')
            date_map[date_str] += 1
            
        time_labels = []
        time_data = []
        current = last_30_days
        while current <= timezone.now():
            d_str = current.strftime('%Y-%m-%d')
            time_labels.append(d_str)
            time_data.append(date_map[d_str])
            current += timedelta(days=1)

    # Years for Filter
    years = BookRequest.objects.dates('timestamp', 'year')
    available_years = [d.year for d in years]

    context = {
        'total_requests': total_requests,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'missed_count': missed_count, # New Metric
        'active_members': active_members,
        'lead_time': lead_time_display,
        'top_books': top_books,
        'top_members': top_members,
        'pie_labels': pie_labels,
        'pie_data': pie_data,
        'time_labels': time_labels,
        'time_data': time_data,
        'title': 'Analytics Dashboard',
        'available_years': available_years,
        'selected_year': int(year) if year else None,
        'selected_month': int(month) if month else None
    }
    return render(request, 'admin_dashboard.html', context)

@staff_member_required
def validate_returns(request):
    """
    Dedicated View for Bib Lit members to validate returned books.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        token = request.POST.get('token', '').strip()
        
        if action == 'search':
            if not token:
                messages.error(request, "Please enter a Token.")
            else:
                try:
                    req = BookRequest.objects.get(token=token, book__type='HC')
                    return render(request, 'library/validate_returns.html', {'search_result': req})
                except BookRequest.DoesNotExist:
                    messages.error(request, "Invalid Token or Not a Hard Copy Request.")
                    
        elif action == 'confirm_return':
            try:
                req = BookRequest.objects.get(token=token)
                
                # Update Request
                req.return_status = 'Returned'
                req.save() # Triggers Book -> Available in models.save()
                
                # Log Action
                ValidateReturns.objects.create(
                    bib_lit_member=request.user.username,
                    action='Return',
                    request_token=token
                )
                
                messages.success(request, f"Book '{req.book.title}' marked as Returned successfully.")
                return redirect('validate_returns')
            except Exception as e:
                messages.error(request, f"Error: {e}")
                
    return render(request, 'library/validate_returns.html')
