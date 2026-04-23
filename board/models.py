import os
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class BoardCategory(models.Model):
    name          = models.CharField(max_length=80)
    icon          = models.CharField(max_length=60, default='fas fa-folder')
    color         = models.CharField(max_length=20, default='#6366f1')
    order         = models.PositiveIntegerField(default=0)
    image         = models.ImageField(upload_to='board/categories/', blank=True, null=True)
    external_link = models.URLField(blank=True, null=True)
    description   = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class BoardTag(models.Model):
    name  = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default='#64748b')

    class Meta:
        ordering = ['name']
        verbose_name = 'Tag'

    def __str__(self):
        return self.name


class BoardPost(models.Model):
    TYPE_GENERAL      = 'general'
    TYPE_WIKI         = 'wiki'
    TYPE_SOP          = 'sop'
    TYPE_FAQ          = 'faq'
    TYPE_LESSON       = 'lesson'
    TYPE_ANNOUNCEMENT = 'announcement'

    TYPE_CHOICES = [
        (TYPE_GENERAL,      'ทั่วไป'),
        (TYPE_WIKI,         'Technical Wiki'),
        (TYPE_SOP,          'SOP'),
        (TYPE_FAQ,          'FAQ'),
        (TYPE_LESSON,       'Lesson Learned'),
        (TYPE_ANNOUNCEMENT, 'ประกาศ'),
    ]

    TYPE_META = {
        TYPE_GENERAL:      {'label': 'ทั่วไป',        'icon': 'fas fa-circle-dot',      'bg': '#f1f5f9', 'color': '#64748b'},
        TYPE_WIKI:         {'label': 'Technical Wiki', 'icon': 'fas fa-book-open',       'bg': '#dbeafe', 'color': '#1d4ed8'},
        TYPE_SOP:          {'label': 'SOP',            'icon': 'fas fa-list-check',      'bg': '#d1fae5', 'color': '#065f46'},
        TYPE_FAQ:          {'label': 'FAQ',            'icon': 'fas fa-circle-question', 'bg': '#fef3c7', 'color': '#92400e'},
        TYPE_LESSON:       {'label': 'Lesson Learned', 'icon': 'fas fa-lightbulb',       'bg': '#f3e8ff', 'color': '#6b21a8'},
        TYPE_ANNOUNCEMENT: {'label': 'ประกาศ',         'icon': 'fas fa-bullhorn',        'bg': '#fee2e2', 'color': '#991b1b'},
    }

    category   = models.ForeignKey(BoardCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_posts')
    title      = models.CharField(max_length=200)
    content    = models.TextField()
    post_type  = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_GENERAL)
    tags       = models.ManyToManyField(BoardTag, blank=True, related_name='posts')
    is_pinned  = models.BooleanField(default=False)
    views      = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        verbose_name = 'Post'

    def __str__(self):
        return self.title

    def comment_count(self):
        return self.comments.filter(parent__isnull=True).count()

    @property
    def type_display(self):
        return self.TYPE_META.get(self.post_type, self.TYPE_META[self.TYPE_GENERAL])


class BoardAttachment(models.Model):
    post        = models.ForeignKey(BoardPost, on_delete=models.CASCADE, related_name='attachments')
    file        = models.FileField(upload_to='board/attachments/')
    name        = models.CharField(max_length=255)
    size        = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='board_attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    _EXT_MAP = {
        '.pdf':  ('fa-file-pdf',        '#ef4444'),
        '.doc':  ('fa-file-word',       '#3b82f6'),
        '.docx': ('fa-file-word',       '#3b82f6'),
        '.xls':  ('fa-file-excel',      '#10b981'),
        '.xlsx': ('fa-file-excel',      '#10b981'),
        '.ppt':  ('fa-file-powerpoint', '#f59e0b'),
        '.pptx': ('fa-file-powerpoint', '#f59e0b'),
        '.zip':  ('fa-file-archive',    '#64748b'),
        '.rar':  ('fa-file-archive',    '#64748b'),
        '.jpg':  ('fa-file-image',      '#8b5cf6'),
        '.jpeg': ('fa-file-image',      '#8b5cf6'),
        '.png':  ('fa-file-image',      '#8b5cf6'),
        '.gif':  ('fa-file-image',      '#8b5cf6'),
    }

    @property
    def ext(self):
        return os.path.splitext(self.name)[1].lower()

    @property
    def size_display(self):
        s = self.size
        if s < 1024:        return f'{s} B'
        if s < 1024 * 1024: return f'{s / 1024:.1f} KB'
        return f'{s / 1024 / 1024:.1f} MB'

    @property
    def icon_info(self):
        fa, color = self._EXT_MAP.get(self.ext, ('fa-file', '#94a3b8'))
        return {'fa': fa, 'color': color}

    def __str__(self):
        return self.name


class BoardComment(models.Model):
    post       = models.ForeignKey(BoardPost, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_comments')
    parent     = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    content    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Comment'

    def __str__(self):
        return f"{self.author.username} → {self.post.title[:40]}"


class BoardAccess(models.Model):
    ROLE_VIEWER    = 'viewer'
    ROLE_EDITOR    = 'editor'
    ROLE_MODERATOR = 'moderator'

    ROLE_CHOICES = [
        (ROLE_VIEWER,    'Viewer — อ่านและแสดงความเห็น'),
        (ROLE_EDITOR,    'Editor — โพสต์ได้'),
        (ROLE_MODERATOR, 'Moderator — จัดการกระดาน'),
    ]

    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='board_access')
    role       = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='granted_accesses')
    granted_at = models.DateTimeField(auto_now_add=True)
    note       = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = 'Board Access'
        verbose_name_plural = 'Board Accesses'

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def can_post(self):
        return self.role in (self.ROLE_EDITOR, self.ROLE_MODERATOR)

    @property
    def can_moderate(self):
        return self.role == self.ROLE_MODERATOR


class BoardLike(models.Model):
    post       = models.ForeignKey(BoardPost, on_delete=models.CASCADE, related_name='likes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')
        verbose_name = 'Like'

    def __str__(self):
        return f"{self.user.username} ❤ {self.post.title[:30]}"
