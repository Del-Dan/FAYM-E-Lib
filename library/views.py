from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from .models import Book, Member, BookRequest
from django.conf import settings
from django.contrib import messages
import uuid

def index(request):
    """Main landing page with search."""
    books = Book.objects.all().order_by('-book_id')[:20] # Show recent
    return render(request, 'library/index.html', {'books': books})

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
