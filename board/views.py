from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.utils.html import strip_tags
from django.db.models import Q, Count

from .models import (BoardCategory, BoardPost, BoardComment,
                     BoardAccess, BoardTag, BoardAttachment, BoardLike)

User = get_user_model()

_COLOR_PRESETS = [
    '#6366f1', '#8b5cf6', '#3b82f6', '#0ea5e9', '#10b981',
    '#f59e0b', '#ef4444', '#ec4899', '#14b8a6', '#64748b',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeAccess:
    role = BoardAccess.ROLE_MODERATOR
    can_post = True
    can_moderate = True


def _get_access(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return _FakeAccess()
    
    # Check global access flag from profile
    try:
        if not getattr(user.profile, 'access_board', False):
            return None
    except Exception:
        return None

    try:
        return user.board_access
    except BoardAccess.DoesNotExist:
        # If user has global access but no granular access record, 
        # we might want to return a default Viewer access or None.
        # Based on the existing logic, it returns None.
        return None


def _require_access(request):
    access = _get_access(request.user)
    if access is None:
        return None, render(request, 'board/no_access.html', status=403)
    return access, None


# ---------------------------------------------------------------------------
# Board list
# ---------------------------------------------------------------------------

@login_required
def board_list(request):
    access, err = _require_access(request)
    if err:
        return err

    q           = request.GET.get('q', '').strip()
    sel_type    = request.GET.get('type', '')
    sel_tag     = request.GET.get('tag', '')
    sel_cat     = request.GET.get('cat', '')
    is_filtered = any([q, sel_type, sel_tag, sel_cat])

    categories = BoardCategory.objects.prefetch_related('posts').all()
    all_tags   = BoardTag.objects.annotate(cnt=Count('posts')).filter(cnt__gt=0).order_by('name')

    posts_qs = (BoardPost.objects
                .select_related('author', 'category')
                .prefetch_related('tags')
                .order_by('-is_pinned', '-created_at'))

    if q:
        posts_qs = posts_qs.filter(
            Q(title__icontains=q) |
            Q(content__icontains=q) |
            Q(tags__name__icontains=q) |
            Q(category__name__icontains=q)
        ).distinct()

    if sel_type:
        posts_qs = posts_qs.filter(post_type=sel_type)

    if sel_tag:
        posts_qs = posts_qs.filter(tags__pk=sel_tag)

    if sel_cat:
        posts_qs = posts_qs.filter(category__pk=sel_cat)

    return render(request, 'board/list.html', {
        'categories':        categories if not is_filtered else [],
        'recent_posts':      posts_qs[:50],
        'all_tags':          all_tags,
        'access':            access,
        'q':                 q,
        'sel_type':          sel_type,
        'sel_tag':           sel_tag,
        'sel_cat':           sel_cat,
        'is_filtered':       is_filtered,
        'post_type_choices': BoardPost.TYPE_CHOICES,
        'post_type_meta':    BoardPost.TYPE_META,
    })


# ---------------------------------------------------------------------------
# Post detail
# ---------------------------------------------------------------------------

@login_required
def board_post_detail(request, pk):
    access, err = _require_access(request)
    if err:
        return err

    post = get_object_or_404(
        BoardPost.objects
        .select_related('author', 'category')
        .prefetch_related('tags', 'attachments__uploaded_by'),
        pk=pk
    )
    post.views += 1
    post.save(update_fields=['views'])

    top_comments = (post.comments.filter(parent__isnull=True)
                    .select_related('author')
                    .prefetch_related('replies__author'))

    # Like state
    user_liked = post.likes.filter(user=request.user).exists()
    like_count = post.likes.count()

    # Related posts (by tag overlap → same category → recent)
    tag_ids = list(post.tags.values_list('pk', flat=True))
    if tag_ids:
        related = (BoardPost.objects
                   .filter(Q(tags__in=tag_ids) | Q(category=post.category))
                   .exclude(pk=post.pk)
                   .select_related('author', 'category')
                   .prefetch_related('tags')
                   .annotate(relevance=Count('tags', filter=Q(tags__in=tag_ids)))
                   .order_by('-relevance', '-created_at')
                   .distinct()[:4])
    elif post.category:
        related = (BoardPost.objects.filter(category=post.category)
                   .exclude(pk=post.pk)
                   .select_related('author', 'category')
                   .prefetch_related('tags')
                   .order_by('-created_at')[:4])
    else:
        related = BoardPost.objects.exclude(pk=post.pk).order_by('-created_at')[:4]

    return render(request, 'board/post_detail.html', {
        'post':         post,
        'top_comments': top_comments,
        'access':       access,
        'user_liked':   user_liked,
        'like_count':   like_count,
        'related':      related,
    })


# ---------------------------------------------------------------------------
# Create post
# ---------------------------------------------------------------------------

@login_required
def board_create_post(request):
    access, err = _require_access(request)
    if err:
        return err

    if not access.can_post:
        messages.error(request, 'คุณไม่มีสิทธิ์สร้างโพสต์')
        return redirect('board:list')

    categories = BoardCategory.objects.all()
    all_tags   = BoardTag.objects.all()

    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        content     = request.POST.get('content', '').strip()
        category_id = request.POST.get('category') or None
        post_type   = request.POST.get('post_type', BoardPost.TYPE_GENERAL)
        is_pinned   = bool(request.POST.get('is_pinned')) and access.can_moderate
        tag_ids     = request.POST.getlist('tags')

        if not title or not strip_tags(content):
            messages.error(request, 'กรุณากรอกหัวข้อและเนื้อหา')
        else:
            post = BoardPost.objects.create(
                author=request.user,
                title=title,
                content=content,
                category_id=category_id,
                post_type=post_type,
                is_pinned=is_pinned,
            )
            if tag_ids:
                post.tags.set(tag_ids)

            for f in request.FILES.getlist('attachments'):
                BoardAttachment.objects.create(
                    post=post, file=f,
                    name=f.name, size=f.size,
                    uploaded_by=request.user,
                )

            messages.success(request, 'สร้างโพสต์เรียบร้อยแล้ว')
            return redirect('board:post_detail', pk=post.pk)

    return render(request, 'board/create_post.html', {
        'categories':        categories,
        'access':            access,
        'all_tags':          all_tags,
        'post_type_choices': BoardPost.TYPE_CHOICES,
        'post_type_meta':    BoardPost.TYPE_META,
    })


# ---------------------------------------------------------------------------
# Edit post
# ---------------------------------------------------------------------------

@login_required
def board_edit_post(request, pk):
    access, err = _require_access(request)
    if err:
        return err

    post = get_object_or_404(BoardPost, pk=pk)

    # only author or moderator can edit
    if not (access.can_moderate or post.author == request.user):
        return HttpResponseForbidden()

    categories = BoardCategory.objects.all()
    all_tags   = BoardTag.objects.all()

    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        content     = request.POST.get('content', '').strip()
        category_id = request.POST.get('category') or None
        post_type   = request.POST.get('post_type', post.post_type)
        is_pinned   = bool(request.POST.get('is_pinned')) and access.can_moderate
        tag_ids     = request.POST.getlist('tags')

        if not title or not strip_tags(content):
            messages.error(request, 'กรุณากรอกหัวข้อและเนื้อหา')
        else:
            post.title       = title
            post.content     = content
            post.category_id = category_id
            post.post_type   = post_type
            post.is_pinned   = is_pinned
            post.save()
            post.tags.set(tag_ids)

            for f in request.FILES.getlist('attachments'):
                BoardAttachment.objects.create(
                    post=post, file=f,
                    name=f.name, size=f.size,
                    uploaded_by=request.user,
                )

            messages.success(request, 'แก้ไขโพสต์เรียบร้อยแล้ว')
            return redirect('board:post_detail', pk=post.pk)

    return render(request, 'board/edit_post.html', {
        'post':              post,
        'categories':        categories,
        'access':            access,
        'all_tags':          all_tags,
        'post_type_choices': BoardPost.TYPE_CHOICES,
        'post_type_meta':    BoardPost.TYPE_META,
    })


# ---------------------------------------------------------------------------
# Delete post
# ---------------------------------------------------------------------------

@login_required
@require_POST
def board_delete_post(request, pk):
    access, err = _require_access(request)
    if err:
        return err

    post = get_object_or_404(BoardPost, pk=pk)
    if not (access.can_moderate or post.author == request.user):
        return HttpResponseForbidden()

    post.delete()
    messages.success(request, 'ลบโพสต์แล้ว')
    return redirect('board:list')


# ---------------------------------------------------------------------------
# Comments (AJAX)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def board_add_comment(request, post_pk):
    access, err = _require_access(request)
    if err:
        return JsonResponse({'ok': False, 'error': 'no_access'}, status=403)

    post      = get_object_or_404(BoardPost, pk=post_pk)
    content   = request.POST.get('content', '').strip()
    parent_id = request.POST.get('parent_id') or None

    if not content:
        return JsonResponse({'ok': False, 'error': 'empty'}, status=400)

    parent = None
    if parent_id:
        parent = get_object_or_404(BoardComment, pk=parent_id, post=post)

    comment = BoardComment.objects.create(
        post=post, author=request.user, parent=parent, content=content,
    )
    return JsonResponse({
        'ok':         True,
        'id':         comment.pk,
        'author':     comment.author.get_full_name() or comment.author.username,
        'content':    comment.content,
        'created_at': comment.created_at.strftime('%d %b %Y %H:%M'),
        'parent_id':  parent_id,
    })


@login_required
@require_POST
def board_delete_comment(request, pk):
    access, err = _require_access(request)
    if err:
        return JsonResponse({'ok': False}, status=403)

    comment = get_object_or_404(BoardComment, pk=pk)
    if not (access.can_moderate or comment.author == request.user):
        return JsonResponse({'ok': False}, status=403)

    comment.delete()
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Attachment delete
# ---------------------------------------------------------------------------

@login_required
@require_POST
def delete_attachment(request, pk):
    access, err = _require_access(request)
    if err:
        return JsonResponse({'ok': False}, status=403)

    att = get_object_or_404(BoardAttachment, pk=pk)
    if not (access.can_moderate or att.uploaded_by == request.user or att.post.author == request.user):
        return JsonResponse({'ok': False}, status=403)

    att.file.delete(save=False)
    att.delete()
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Tag management
# ---------------------------------------------------------------------------

@login_required
def tag_manage(request):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        return redirect('board:list')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name  = request.POST.get('name', '').strip()
            color = request.POST.get('color', '#64748b').strip()
            if name:
                _, created = BoardTag.objects.get_or_create(name=name, defaults={'color': color})
                if created:
                    messages.success(request, f'สร้าง tag "{name}" แล้ว')
                else:
                    messages.warning(request, f'Tag "{name}" มีอยู่แล้ว')

        elif action == 'delete':
            BoardTag.objects.filter(pk=request.POST.get('tag_id')).delete()
            messages.success(request, 'ลบ tag แล้ว')

        elif action == 'update_color':
            tag = get_object_or_404(BoardTag, pk=request.POST.get('tag_id'))
            tag.color = request.POST.get('color', tag.color)
            tag.save()

        return redirect('board:tag_manage')

    tags = BoardTag.objects.annotate(cnt=Count('posts')).order_by('name')
    return render(request, 'board/tag_manage.html', {
        'tags':          tags,
        'access':        access,
        'color_presets': _COLOR_PRESETS,
    })


# ---------------------------------------------------------------------------
# Manage access
# ---------------------------------------------------------------------------

@login_required
def board_manage_access(request):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        messages.error(request, 'เฉพาะ Moderator เท่านั้น')
        return redirect('board:list')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'grant':
            username = request.POST.get('username', '').strip()
            role     = request.POST.get('role', BoardAccess.ROLE_VIEWER)
            note     = request.POST.get('note', '').strip()
            try:
                target = User.objects.get(username=username)
                obj, created = BoardAccess.objects.update_or_create(
                    user=target,
                    defaults={'role': role, 'granted_by': request.user, 'note': note},
                )
                messages.success(request, f"{'เพิ่ม' if created else 'อัปเดต'}สิทธิ์ {target.username} เป็น {role}")
            except User.DoesNotExist:
                messages.error(request, f'ไม่พบ user: {username}')

        elif action == 'revoke':
            BoardAccess.objects.filter(pk=request.POST.get('access_id')).delete()
            messages.success(request, 'ยกเลิกสิทธิ์แล้ว')

        return redirect('board:manage_access')

    all_access = BoardAccess.objects.select_related('user', 'granted_by').order_by('role', 'user__username')
    granted_ids = set(all_access.values_list('user_id', flat=True))
    all_users = (User.objects.filter(is_active=True)
                 .exclude(pk__in=granted_ids)
                 .exclude(pk=request.user.pk)
                 .order_by('first_name', 'username'))

    return render(request, 'board/manage_access.html', {
        'all_access':   all_access,
        'access':       access,
        'role_choices': BoardAccess.ROLE_CHOICES,
        'all_users':    all_users,
    })


# ---------------------------------------------------------------------------
# Like toggle
# ---------------------------------------------------------------------------

@login_required
@require_POST
def toggle_like(request, pk):
    access, err = _require_access(request)
    if err:
        return JsonResponse({'ok': False}, status=403)

    post = get_object_or_404(BoardPost, pk=pk)
    like, created = BoardLike.objects.get_or_create(post=post, user=request.user)
    if not created:
        like.delete()
        liked = False
    else:
        liked = True

    return JsonResponse({'ok': True, 'liked': liked, 'count': post.likes.count()})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def board_dashboard(request):
    access, err = _require_access(request)
    if err:
        return err

    from django.utils import timezone
    from datetime import timedelta

    thirty_ago = timezone.now() - timedelta(days=30)

    total_posts    = BoardPost.objects.count()
    total_comments = BoardComment.objects.count()
    total_views    = BoardPost.objects.aggregate(v=Count('views'))['v'] or 0
    total_likes    = BoardLike.objects.count()
    new_this_month = BoardPost.objects.filter(created_at__gte=thirty_ago).count()

    top_viewed    = (BoardPost.objects.select_related('author', 'category')
                    .order_by('-views')[:6])
    top_liked     = (BoardPost.objects.select_related('author', 'category')
                    .annotate(like_cnt=Count('likes')).order_by('-like_cnt')[:6])
    top_commented = (BoardPost.objects.select_related('author', 'category')
                    .annotate(cmt_cnt=Count('comments', filter=Q(comments__parent__isnull=True)))
                    .order_by('-cmt_cnt')[:6])

    top_contributors = (User.objects
                        .annotate(post_cnt=Count('board_posts', distinct=True),
                                  like_cnt=Count('board_posts__likes', distinct=True))
                        .filter(post_cnt__gt=0)
                        .order_by('-post_cnt', '-like_cnt')[:10])

    # Post type distribution
    type_data = []
    for val, _ in BoardPost.TYPE_CHOICES:
        cnt  = BoardPost.objects.filter(post_type=val).count()
        meta = BoardPost.TYPE_META[val]
        type_data.append({**meta, 'val': val, 'count': cnt})
    max_cnt = max((x['count'] for x in type_data), default=1) or 1
    for x in type_data:
        x['pct'] = round(x['count'] / max_cnt * 100)
    type_data.sort(key=lambda x: -x['count'])

    top_tags    = BoardTag.objects.annotate(cnt=Count('posts')).filter(cnt__gt=0).order_by('-cnt')[:15]
    recent_posts = (BoardPost.objects.select_related('author', 'category')
                   .prefetch_related('tags').order_by('-created_at')[:8])

    return render(request, 'board/dashboard.html', {
        'access':           access,
        'total_posts':      total_posts,
        'total_comments':   total_comments,
        'total_views':      total_views,
        'total_likes':      total_likes,
        'new_this_month':   new_this_month,
        'top_viewed':       top_viewed,
        'top_liked':        top_liked,
        'top_commented':    top_commented,
        'top_contributors': top_contributors,
        'type_data':        type_data,
        'top_tags':         top_tags,
        'recent_posts':     recent_posts,
    })


# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------

def _cat_form_ctx(access, cat):
    return {'access': access, 'cat': cat, 'color_presets': _COLOR_PRESETS}


@login_required
def category_list(request):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        return redirect('board:list')
    return render(request, 'board/category_manage.html', {
        'categories': BoardCategory.objects.all(),
        'access': access,
    })


@login_required
def category_create(request):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        return redirect('board:list')

    if request.method == 'POST':
        name          = request.POST.get('name', '').strip()
        icon          = request.POST.get('icon', 'fas fa-folder').strip()
        color         = request.POST.get('color', '#6366f1').strip()
        order         = int(request.POST.get('order', 0) or 0)
        description   = request.POST.get('description', '').strip()
        external_link = request.POST.get('external_link', '').strip() or None
        image         = request.FILES.get('image')
        if name:
            cat = BoardCategory.objects.create(
                name=name, icon=icon, color=color, order=order,
                description=description, external_link=external_link,
            )
            if image:
                cat.image = image
                cat.save()
            messages.success(request, f'เพิ่มหมวดหมู่ "{name}" แล้ว')
        return redirect('board:category_list')
    return render(request, 'board/category_form.html', _cat_form_ctx(access, None))


@login_required
def category_edit(request, pk):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        return redirect('board:list')

    cat = get_object_or_404(BoardCategory, pk=pk)
    if request.method == 'POST':
        cat.name          = request.POST.get('name', '').strip() or cat.name
        cat.icon          = request.POST.get('icon', cat.icon).strip()
        cat.color         = request.POST.get('color', cat.color).strip()
        cat.order         = int(request.POST.get('order', cat.order) or cat.order)
        cat.description   = request.POST.get('description', '').strip()
        cat.external_link = request.POST.get('external_link', '').strip() or None
        if request.FILES.get('image'):
            cat.image = request.FILES['image']
        if request.POST.get('clear_image'):
            cat.image = None
        cat.save()
        messages.success(request, f'อัปเดต "{cat.name}" แล้ว')
        return redirect('board:category_list')
    return render(request, 'board/category_form.html', _cat_form_ctx(access, cat))


@login_required
@require_POST
def category_delete(request, pk):
    access, err = _require_access(request)
    if err:
        return err
    if not access.can_moderate:
        return redirect('board:list')
    cat = get_object_or_404(BoardCategory, pk=pk)
    name = cat.name
    cat.delete()
    messages.success(request, f'ลบหมวดหมู่ "{name}" แล้ว')
    return redirect('board:category_list')


# ---------------------------------------------------------------------------
# Image upload (CKEditor)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def upload_image(request):
    access, err = _require_access(request)
    if err:
        return JsonResponse({'error': {'message': 'no_access'}}, status=403)

    image = request.FILES.get('upload')
    if not image:
        return JsonResponse({'error': {'message': 'no file'}}, status=400)

    from django.core.files.storage import default_storage
    import uuid
    ext  = '.' + image.name.rsplit('.', 1)[-1].lower() if '.' in image.name else ''
    name = f'board/uploads/{uuid.uuid4().hex}{ext}'
    path = default_storage.save(name, image)
    return JsonResponse({'url': default_storage.url(path)})
