from django.contrib import admin
from .models import BoardCategory, BoardPost, BoardComment, BoardAccess, BoardTag, BoardAttachment, BoardLike


@admin.register(BoardCategory)
class BoardCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'color', 'order')
    ordering = ('order', 'name')


@admin.register(BoardTag)
class BoardTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color')
    search_fields = ('name',)


@admin.register(BoardPost)
class BoardPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'post_type', 'author', 'category', 'is_pinned', 'views', 'created_at')
    list_filter = ('post_type', 'category', 'is_pinned')
    search_fields = ('title', 'author__username')
    filter_horizontal = ('tags',)
    date_hierarchy = 'created_at'


@admin.register(BoardAttachment)
class BoardAttachmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'post', 'uploaded_by', 'size', 'uploaded_at')
    search_fields = ('name', 'post__title')


@admin.register(BoardLike)
class BoardLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'post', 'created_at')
    search_fields = ('user__username', 'post__title')


@admin.register(BoardComment)
class BoardCommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'post', 'parent', 'created_at')
    search_fields = ('author__username', 'content')


@admin.register(BoardAccess)
class BoardAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'granted_by', 'granted_at', 'note')
    list_filter = ('role',)
    search_fields = ('user__username', 'note')
