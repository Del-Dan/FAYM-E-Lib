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
    list_display = ('token', 'full_name', 'book', 'request_status', 'approval_status', 'timestamp')
    list_filter = ('request_status', 'approval_status', 'return_status')
    search_fields = ('token', 'email', 'full_name')
    readonly_fields = ('token', 'timestamp', 'days_left')

@admin.register(ValidateReturns)
class ValidateReturnsAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'book_title_snapshot', 'bib_lit_member')
    list_filter = ('action',)
