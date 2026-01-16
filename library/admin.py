from django.contrib import admin
from .models import Member, Book, BookRequest, ReturnLog

@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('firstname', 'surname', 'email', 'mobile_number', 'residence')
    search_fields = ('firstname', 'surname', 'email', 'mobile_number')

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'type', 'availability', 'location', 'owner')
    list_filter = ('type', 'availability')
    search_fields = ('title', 'author', 'keywords')

@admin.register(BookRequest)
class BookRequestAdmin(admin.ModelAdmin):
    list_display = ('token', 'member_link', 'book', 'request_status', 'approval_status', 'timestamp')
    list_filter = ('approval_status', 'request_status') # Removed return_status from filter to reduce noise
    search_fields = ('token', 'email', 'full_name', 'member__firstname', 'member__surname')
    
    # Read-only fields (Exclude return_status entirely from edit form)
    readonly_fields = ('token', 'timestamp', 'days_left', 'full_name', 'email', 'member', 'book', 'approval_date', 'expected_return_date')
    exclude = ('return_status',) # System field only
    
    # Enable Autocomplete for initial selection (though they become read-only later)
    autocomplete_fields = ['member', 'book']

    def member_link(self, obj):
        return obj.member
    member_link.short_description = 'Member'

    def save_model(self, request, obj, form, change):
        # Auto-populate legacy fields from Relation
        if obj.member and not obj.full_name:
            obj.full_name = f"{obj.member.firstname} {obj.member.surname}"
            obj.email = obj.member.email
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        # If object exists (Editing), lock everything critical
        if obj:
            return self.readonly_fields
        # If creating new, allow selection of Member/Book
        return ('token', 'timestamp', 'days_left', 'full_name', 'email', 'approval_date', 'expected_return_date')

@admin.register(ReturnLog)
class ReturnLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'book_title_snapshot', 'bib_lit_member')
    list_filter = ('action',)
