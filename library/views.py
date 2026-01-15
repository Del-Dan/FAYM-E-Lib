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
    """Generate OTP using Wigal Frog v3."""
    api_key = settings.WIGAL_API_KEY
    username = settings.WIGAL_USERNAME
    sender_id = settings.WIGAL_SENDER_ID
    
    url = 'https://frogapi.wigal.com.gh/api/v3/sms/otp/generate'
    
    # Format Phone
    clean_phone = str(phone).strip()
    clean_phone = ''.join(filter(str.isdigit, clean_phone))
    if len(clean_phone) == 10 and clean_phone.startswith('0'):
        clean_phone = '233' + clean_phone[1:]
    elif len(clean_phone) == 9:
        clean_phone = '233' + clean_phone
        
    payload = {
        "senderid": sender_id,
        "number": clean_phone,
        "expiry": 5, # 5 minutes validity
        "length": 6,
        "type": "NUMERIC",
        "messagetemplate": "Your FAYM Library OTP is %OTPCODE%. Valid for %EXPIRY% minutes."
    }
    
    headers = {'Content-Type': 'application/json', 'API-KEY': api_key, 'USERNAME': username}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        print(f"OTP Generate Response: {data}")
        return data.get('otpcode') if response.status_code == 200 else None
        # Note: In real production, usually API sends the SMS. 
        # But if the API returns the code (which some do for verification), we store it.
        # Wigal Verify endpoint might handle the verification logic itself.
        # Checking logic: The generated OTP is SENT to the user by Wigal. 
        # We might not get the code back in response for security. 
        # If Wigal handles verification, we use their verify endpoint.
        # Let's assume we use Wigal's verify endpoint.
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
    """HTMX View to trigger OTP sending."""
    identity = request.POST.get('identity', '').strip()
    
    # Check Member
    member = Member.objects.filter(
        Q(email__iexact=identity) | 
        Q(mobile_number__iexact=identity)
    ).first()
    
    if not member:
        return JsonResponse({'status': 'error', 'message': 'Member not found.'})
    
    # Generate Code via Wigal (or self-generate if Wigal just sends msg)
    # Wigal Generate endpoint actually returns the code it sent? 
    # Yes, based on docs it returns {status, message, otpcode}.
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
        
        # We still rely on user session to know WHICH phone they are claiming to be
        request.session['otp_phone'] = member.mobile_number
        return JsonResponse({'status': 'sent', 'message': f'OTP sent to {member.mobile_number}'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Failed to send OTP.'})

def verify_otp_action(request):
    """HTMX View to verify OTP input."""
    code = request.POST.get('otp_code', '').strip()
    phone = request.session.get('otp_phone')
    
    if not phone:
         return JsonResponse({'status': 'error', 'message': 'Session expired. Request OTP again.'})
         
    # DB Verification
    record = OTPRecord.objects.filter(
        phone_number=phone,
        otp_code=code,
        is_verified=False,
        expires_at__gt=timezone.now()
    ).first()
    
    if record:
        record.is_verified = True
        record.save()
        
        # Set Session (30 mins)
        request.session['is_verified'] = True
        request.session['verified_identity'] = phone
        request.session['session_expiry'] = (timezone.now() + timedelta(minutes=30)).isoformat()
        return JsonResponse({'status': 'success', 'message': 'Verified!'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid or Expired OTP.'})

def check_request_limits(member, book_type):
    """
    Enforce limits:
    - SC: Max 2 per week, Max 4 per month.
    - HC: Max 1 active request until returned.
    """
    now = timezone.now()
    email = member.email
    
    if book_type == 'SC':
        # Check Weekly (Last 7 days)
        week_ago = now - timedelta(days=7)
        week_count = BookRequest.objects.filter(
            email=email, 
            book__type='SC', 
            timestamp__gte=week_ago
        ).count()
        
        if week_count >= 2:
            return "Limit Reached: You can only request 2 Soft Copy books per week."
            
        # Check Monthly (Last 30 days)
        month_ago = now - timedelta(days=30)
        month_count = BookRequest.objects.filter(
            email=email, 
            book__type='SC', 
            timestamp__gte=month_ago
        ).count()
        
        if month_count >= 4:
            return "Limit Reached: You can only request 4 Soft Copy books per month."
            
    elif book_type == 'HC':
        # Check Active HC requests (Not Returned)
        # Assuming 'Returned' or 'N/A' means closed.
        active_hc = BookRequest.objects.filter(
            email=email,
            book__type='HC'
        ).exclude(return_status='Returned').exists()
        
        if active_hc:
            return "Limit Reached: You have an unreturned Hard Copy book. Please return it first."
            
    return None

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
             # Expired
             del request.session['is_verified']
             del request.session['session_expiry']
             messages.error(request, "Security Session Expired. Please verify via OTP.")
             return redirect('index')
        # --------------------------

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
            
        # --- NEW: Request Limits Check ---
        limit_error = check_request_limits(member, book.type)
        if limit_error:
            messages.error(request, limit_error)
            return redirect('index')
        # ---------------------------------

        # Create Request
        req = BookRequest.objects.create(
            member=member, # Link Relational Data
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
        return redirect('index')
        
    return redirect('index')

@staff_member_required
def admin_dashboard_view(request):
    """
    Detailed Analytics Dashboard for Stats & Insights.
    """
    # 1. KPI Counts
    total_requests = BookRequest.objects.count()
    approved_count = BookRequest.objects.filter(approval_status='Approved').count()
    pending_count = BookRequest.objects.filter(approval_status='Pending').count()
    active_members = Member.objects.count() # Total database members
    
    # 1b. Lead Time (Avg Duration from Request to Approval)
    from django.db.models import Avg, F, DurationField, ExpressionWrapper
    # SQLite/Postgres difference in duration math. Django handles it mostly.
    # We only care about Approved ones with a date.
    # Note: If approval_date is null, we skip.
    
    valid_approvals = BookRequest.objects.filter(approval_status='Approved', approval_date__isnull=False)
    # Python calc is often safer for cross-db compatibility with durations if volume is low.
    lead_times = [(r.approval_date - r.timestamp).total_seconds() for r in valid_approvals]
    
    if lead_times:
        avg_seconds = sum(lead_times) / len(lead_times)
        avg_hours = round(avg_seconds / 3600, 1)
        lead_time_display = f"{avg_hours} Hours"
    else:
        lead_time_display = "N/A"

    # 2. Top Books (Most Requested)
    top_books = BookRequest.objects.values('book__title').annotate(count=Count('id')).order_by('-count')[:5]

    # 3. Top Members (Most Active)
    top_members = BookRequest.objects.values('full_name').annotate(count=Count('id')).order_by('-count')[:5]

    # 4. Pie Chart Data (Status Distribution)
    status_counts = BookRequest.objects.values('approval_status').annotate(count=Count('id'))
    pie_labels = [item['approval_status'] for item in status_counts]
    pie_data = [item['count'] for item in status_counts]

    # 5. Line Chart (Requests over last 30 days)
    # Group by date
    last_30_days = timezone.now() - timedelta(days=30)
    
    # SQLite/Postgres date truncation varies. 
    # For safety/portability, we'll fetch and process in python (if dataset is small < 10k) OR use distinct logic.
    daily_qs = BookRequest.objects.filter(timestamp__gte=last_30_days).values_list('timestamp', flat=True)
    
    # Process dates
    from collections import defaultdict
    date_map = defaultdict(int)
    for ts in daily_qs:
        date_str = ts.strftime('%Y-%m-%d')
        date_map[date_str] += 1
        
    # Generate continuous timeline
    time_labels = []
    time_data = []
    current = last_30_days
    while current <= timezone.now():
        d_str = current.strftime('%Y-%m-%d')
        time_labels.append(d_str)
        time_data.append(date_map[d_str])
        current += timedelta(days=1)

    context = {
        'total_requests': total_requests,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'active_members': active_members,
        'lead_time': lead_time_display,
        'top_books': top_books,
        'top_members': top_members,
        'pie_labels': pie_labels,
        'pie_data': pie_data,
        'time_labels': time_labels,
        'time_data': time_data,
        'title': 'Analytics Dashboard'
    }
    return render(request, 'admin_dashboard.html', context)
