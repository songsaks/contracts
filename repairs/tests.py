from django.test import TestCase, Client
from django.urls import reverse
from .models import Customer, Device, RepairJob, RepairItem, Technician

class RepairSystemTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.technician = Technician.objects.create(name="Tech User", expertise="General")

    def test_customer_creation(self):
        """Test if customer is created correctly"""
        customer = Customer.objects.create(name="John Test", contact_number="0812345678", address="Test Address")
        self.assertTrue(customer.customer_code.startswith("C"))
        self.assertEqual(customer.name, "John Test")

    def test_repair_create_view_post(self):
        """Test creating a new repair job via the view"""
        url = reverse('repairs:repair_create')
        data = {
            'customer-name': 'Jane Doe',
            'customer-contact_number': '0987654321',
            'customer-address': 'Jane Address',
            'job-fix_id': 'FIX123',
            'device-brand': 'Samsung',
            'device-model': 'Galaxy S23',
            'device-serial_number': 'SN12345',
            'device-device_type': 'Mobile',
            'item-issue_description': 'Screen broken',
            'item-status': 'RECEIVED',
            'item-price': '500.00',
            'item-technicians': [self.technician.id]
        }
        response = self.client.post(url, data)
        
        # Check if redirected (success)
        self.assertEqual(response.status_code, 302)
        
        # Verify DB objects
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(RepairJob.objects.count(), 1)
        self.assertEqual(RepairItem.objects.count(), 1)
        
        job = RepairJob.objects.first()
        self.assertEqual(job.fix_id, 'FIX123')
        self.assertTrue(job.job_code.startswith('J'))

    def test_repair_list_view(self):
        """Test that list view renders correctly"""
        url = reverse('repairs:repair_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'repairs/repair_list.html')

    def test_repair_detail_view(self):
        """Test detail view"""
        customer = Customer.objects.create(name="John Test", contact_number="0812345678")
        job = RepairJob.objects.create(customer=customer)
        device = Device.objects.create(customer=customer, brand="Test", model="Phone", device_type="Mobile")
        RepairItem.objects.create(job=job, device=device, issue_description="Broken", status="RECEIVED")

        url = reverse('repairs:repair_detail', args=[job.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Test")
        self.assertContains(response, job.job_code)

    def test_update_status(self):
        """Test updating item status"""
        customer = Customer.objects.create(name="John Test", contact_number="0812345678")
        job = RepairJob.objects.create(customer=customer)
        device = Device.objects.create(customer=customer, brand="Test", model="Phone", device_type="Mobile")
        item = RepairItem.objects.create(job=job, device=device, issue_description="Broken", status="RECEIVED")
        
        url = reverse('repairs:repair_update_status', args=[item.id])
        response = self.client.post(url, {'status': 'FIXING'})
        
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, 'FIXING')
