from django.contrib import admin
from .models import Member, Book, BookRequest, ValidateReturns

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
    list_filter = ('request_status', 'approval_status', 'return_status')
    search_fields = ('token', 'email', 'full_name', 'member__firstname', 'member__surname')
    readonly_fields = ('token', 'timestamp', 'days_left', 'full_name', 'email')
    
    # Enable Autocomplete (Performance + UX)
    autocomplete_fields = ['member', 'book']

    def member_link(self, obj):
        return obj.member
    member_link.short_description = 'Member'

    def save_model(self, request, obj, form, change):
        # Auto-populate legacy fields from Relation
        if obj.member:
            obj.full_name = f"{obj.member.firstname} {obj.member.surname}"
            obj.email = obj.member.email
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        # Lock fields after creation to ensure integrity
        if obj:
            return self.readonly_fields + ('member', 'book')
        return self.readonly_fields

@admin.register(ValidateReturns)
class ValidateReturnsAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'book_title_snapshot', 'bib_lit_member')
    list_filter = ('action',)
