from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('search/', views.search_books, name='search_books'),
    path('check-member/', views.check_member, name='check_member'),
    path('request/', views.submit_request, name='submit_request'),
    path('bulk-import/', views.bulk_import, name='bulk_import'),
    path('suggest-books/', views.suggest_books, name='suggest_books'),
    path('send-otp/', views.send_otp, name='send_otp'),
    path('verify-otp/', views.verify_otp_action, name='verify_otp'),
    path('dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('validate-returns/', views.validate_returns, name='validate_returns'),
]
