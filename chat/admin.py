from django.contrib import admin
from .models import ChatRoom, ChatMessage

# ลงทะเบียนโมเดล ChatRoom ในหน้า Admin
@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'app_category', 'project', 'is_private', 'is_active', 'created_at')
    list_filter = ('app_category', 'is_private', 'is_active', 'created_at')
    search_fields = ('name', 'description')
    filter_horizontal = ('allowed_users',)

# ลงทะเบียนโมเดล ChatMessage ในหน้า Admin
@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('user', 'room', 'content_snippet', 'timestamp', 'is_speech_to_text')
    list_filter = ('room', 'timestamp', 'is_speech_to_text')
    search_fields = ('content', 'user__username')

    def content_snippet(self, obj):
        return obj.content[:50]
    content_snippet.short_description = "เนื้อหาข้อความ"
