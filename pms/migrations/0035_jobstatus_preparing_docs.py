from django.db import migrations


def add_preparing_docs_job_statuses(apps, schema_editor):
    JobStatus = apps.get_model('pms', 'JobStatus')

    # SERVICE: insert between DELIVERY (50) and WAITING_FOR_SALE_KEY (60)
    JobStatus.objects.get_or_create(
        job_type='SERVICE',
        status_key='PREPARING_DOCS',
        defaults={
            'label': 'เตรียมเอกสารใบส่งสินค้า',
            'sort_order': 55,
            'is_active': True,
        }
    )

    # PROJECT: insert between INSTALLATION (70) and WAITING_FOR_SALE_KEY (80)
    JobStatus.objects.get_or_create(
        job_type='PROJECT',
        status_key='PREPARING_DOCS',
        defaults={
            'label': 'เตรียมเอกสารใบส่งสินค้า',
            'sort_order': 75,
            'is_active': True,
        }
    )

    # REPAIR: insert between DELIVERY (60) and WAITING_FOR_SALE_KEY (70)
    JobStatus.objects.get_or_create(
        job_type='REPAIR',
        status_key='PREPARING_DOCS',
        defaults={
            'label': 'เตรียมเอกสารใบส่งสินค้า',
            'sort_order': 65,
            'is_active': True,
        }
    )


def remove_preparing_docs_job_statuses(apps, schema_editor):
    JobStatus = apps.get_model('pms', 'JobStatus')
    JobStatus.objects.filter(status_key='PREPARING_DOCS').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pms', '0034_add_preparing_docs_status'),
    ]

    operations = [
        migrations.RunPython(
            add_preparing_docs_job_statuses,
            remove_preparing_docs_job_statuses,
        ),
    ]
