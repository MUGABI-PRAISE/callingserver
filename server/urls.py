# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("test/", views.test_page, name="test_page"),
    path("test_chat/", views.test_chat_server, name="test_chat_server"),
]
