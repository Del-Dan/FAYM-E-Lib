from django.db import models
import uuid
from django.utils import timezone
from datetime import timedelta
import dropbox
import os
from django.core.exceptions import ValidationError

class Member(models.Model):
    firstname = models.CharField(max_length=100)
    surname = models.CharField(max_length=100)
    othernames = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=20, unique=True)
    residence = models.CharField(max_length=200, blank=True, null=True)
    landmark = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.firstname} {self.surname}"

class Book(models.Model):
    TYPE_CHOICES = [
        ('SC', 'Soft Copy'),
        ('HC', 'Hard Copy'),
    ]
    AVAILABILITY_CHOICES = [
        ('Available', 'Available'),
        ('On Hold', 'On Hold'),
        ('Taken', 'Taken'),
        ('Not Available', 'Not Available'), # Keep for legacy/manual
    ]

    book_id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=2, choices=TYPE_CHOICES)
    author = models.CharField(max_length=200)
    owner = models.CharField(max_length=200, help_text="Name of owner if HC, else FAYM")
    location = models.CharField(max_length=500, help_text="Physical location or Dropbox Link")
    duration_days = models.IntegerField(default=7, help_text="Keep duration in days for HC")
    availability = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES, default='Available')
    keywords = models.TextField(help_text="Comma separated keywords")
    
    # Virtual field for uploading
    file_upload = models.FileField(upload_to='temp_books/', blank=True, null=True, help_text="Upload SC file here. It will be moved to Dropbox.")
    cover_url = models.URLField(blank=True, null=True, help_text="URL to book cover image")

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Dropbox Integration Logic
        if self.file_upload:
            try:
                dbx_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
                if not dbx_token:
                    # Fallback or Error if strict. for now print
                    print("Dropbox Token missing, skipping upload.")
                else:
                    dbx = dropbox.Dropbox(dbx_token)
                    
                    # Read file
                    file_data = self.file_upload.read()
                    file_name = self.file_upload.name
                    
                    # Upload
                    upload_path = f"/{file_name}" # Root or specify folder
                    res = dbx.files_upload(file_data, upload_path, mode=dropbox.files.WriteMode.overwrite)
                    
                    # Create Shared Link
                    try:
                        link_meta = dbx.sharing_create_shared_link_with_settings(upload_path)
                        self.location = link_meta.url
                    except dropbox.exceptions.ApiError:
                        # Link might exist
                        links = dbx.sharing_list_shared_links(path=upload_path).links
                        if links:
                            self.location = links[0].url
                            
                    # Force Type SC
                    self.type = 'SC'
                    # Clear file to save space (optional, or keep as backup?)
                    # self.file_upload = None 
            except Exception as e:
                print(f"Dropbox Error: {e}")
                # Don't block save, but maybe log it
                
        super().save(*args, **kwargs)

    @property
    def is_available(self):
        return self.availability == 'Available'

class BookRequest(models.Model):
    REQUEST_STATUS_CHOICES = [
        ('Valid', 'Valid'),
        ('Invalid', 'Invalid'),
    ]
    APPROVAL_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Not Approved', 'Not Approved'),
        ('Expired', 'Expired'),
    ]
    RETURN_STATUS_CHOICES = [
        ('Returned', 'Returned'),
        ('Pending', 'Pending'),
        ('Due', 'Due'),
        ('Overdue', 'Overdue'),
        ('N/A', 'Not Applicable (SC)'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    token = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    
    # Link to actual Member record for relational integrity
    member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name='requests')
    
    # Legacy/Fallback string fields (keep for history)
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    
    book = models.ForeignKey(Book, on_delete=models.CASCADE, null=True)
    request_status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default='Valid')
    approval_status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='Pending')
    approval_date = models.DateTimeField(null=True, blank=True)
    
    # HC Specifics
    delivery_date = models.DateTimeField(null=True, blank=True)
    expected_return_date = models.DateTimeField(null=True, blank=True)
    return_status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='Pending')
    
    # Computed fields logic will be in methods/signals
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = str(uuid.uuid4())
        
        # SC logic: No return status
        if self.book and self.book.type == 'SC':
            self.return_status = 'N/A'
            if self.approval_status == 'Approved' and not self.approval_date:
                self.approval_date = timezone.now()

        # HC Logic: State Machine
        if self.book and self.book.type == 'HC':
            # 1. On Hold Logic (Pending)
            if self.approval_status == 'Pending':
                 if self.book.availability == 'Available':
                     self.book.availability = 'On Hold'
                     self.book.save()
            
            # 2. Taken Logic (Approved)
            elif self.approval_status == 'Approved':
                 if not self.approval_date:
                     self.approval_date = timezone.now()
                 if not self.delivery_date:
                     self.delivery_date = timezone.now() # Default to now if not set
                     
                 # Auto-calculate expected return date
                 if not self.expected_return_date:
                     self.expected_return_date = self.delivery_date + timedelta(days=self.book.duration_days)
                 
                 self.book.availability = 'Taken'
                 self.book.save()

            # 3. Released Logic (Rejected/Expired/Invalid)
            elif self.approval_status in ['Not Approved', 'Expired'] or self.request_status == 'Invalid':
                 self.book.availability = 'Available'
                 self.book.save()
                 
            # 4. Returned Logic
            if self.return_status == 'Returned':
                 self.book.availability = 'Available'
                 self.book.save()
            
        super().save(*args, **kwargs)

    @property
    def days_left(self):
        if self.expected_return_date and self.return_status not in ['Returned', 'N/A']:
            delta = self.expected_return_date - timezone.now()
            return delta.days
        return None

    def __str__(self):
        return f"{self.token} - {self.book.title if self.book else 'Unknown'}"

class ValidateReturns(models.Model):
    ACTION_CHOICES = [
        ('Approval', 'Approval'),
        ('Return', 'Return'),
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True)
    bib_lit_member = models.CharField(max_length=200)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    request_token = models.CharField(max_length=50) # Link by token string
    date_of_action = models.DateField(default=timezone.now)
    
    # Snapshot fields (in case book/request changes)
    book_title_snapshot = models.CharField(max_length=200, blank=True)
    request_date_snapshot = models.DateTimeField(null=True)
    
    def save(self, *args, **kwargs):
        # Auto-populate snapshots from token if possible
        if not self.book_title_snapshot:
            try:
                req = BookRequest.objects.get(token=self.request_token)
                if req.book:
                    self.book_title_snapshot = req.book.title
                self.request_date_snapshot = req.timestamp
            except BookRequest.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    @property
    def lead_time(self):
        # Calculation logic
        if self.action == 'Approval' and self.request_date_snapshot:
             delta = self.timestamp - self.request_date_snapshot
             return delta.days
        # For returns, need logic: Timestamp - Date of Action? 
        return 0

class OTPRecord(models.Model):
    phone_number = models.CharField(max_length=20)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    
    def is_valid(self):
        return timezone.now() < self.expires_at and not self.is_verified
        
    def __str__(self):
        return f"{self.phone_number} - {self.otp_code}"
