from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('search/', views.search_books, name='search_books'),
    path('check-member/', views.check_member, name='check_member'),
    path('request/', views.submit_request, name='submit_request'),
]
