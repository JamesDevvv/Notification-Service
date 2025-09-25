"""
Load test script for the notification service.
Sends 1000 mixed notifications and measures throughput.

Usage:
1. Start the notification service (local or Docker)
2. Run: python -m tests.load_test
"""

import asyncio
import time
from typing import List, Dict, Any

import httpx # type: ignore


BASE_URL = "http://localhost:8000"
TOTAL_NOTIFICATIONS = 1000


def generate_test_notifications() -> List[Dict[str, Any]]:
    """Generate a mix of notification requests for load testing."""
    notifications = []
    
    # Mix of channels and priorities
    channels = ["email", "sms", "webhook", "push"]
    priorities = ["low", "normal", "high", "critical"]
    
    for i in range(TOTAL_NOTIFICATIONS):
        channel = channels[i % len(channels)]
        priority = priorities[i % len(priorities)]
        
        if channel == "email":
            recipient = f"user{i}@example.com"
            content = {"subject": f"Test Email {i}", "body": f"This is test email number {i}"}
        elif channel == "sms":
            recipient = f"+1555123{i:04d}"
            content = {"body": f"Test SMS {i}"}
        elif channel == "webhook":
            recipient = f"https://httpbin.org/post?id={i}"
            content = {"body": f"Test webhook {i}"}
        else:  # push
            recipient = f"TESTTOKEN_{i:010d}_abcdef"
            content = {"body": f"Test push {i}"}
        
        notifications.append({
            "channel": channel,
            "recipient": recipient,
            "content": content,
            "priority": priority,
            "metadata": {"test_id": i}
        })
    
    return notifications


async def send_notification_batch(client: httpx.AsyncClient, notifications: List[Dict[str, Any]]) -> List[str]:
    """Send a batch of notifications and return tracking IDs."""
    tracking_ids = []
    
    for notif in notifications:
        try:
            resp = await client.post("/notifications/send", json=notif)
            if resp.status_code == 200:
                data = resp.json()
                tracking_ids.append(data["tracking_id"])
            else:
                print(f"Failed to send notification: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"Error sending notification: {e}")
    
    return tracking_ids


async def check_delivery_status(client: httpx.AsyncClient, tracking_ids: List[str]) -> Dict[str, int]:
    """Check delivery status of notifications and return counts by status."""
    status_counts = {"delivered": 0, "failed": 0, "queued": 0, "sending": 0, "bounced": 0}
    
    for tid in tracking_ids:
        try:
            resp = await client.get(f"/notifications/{tid}/status")
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            else:
                status_counts["failed"] += 1
        except Exception as e:
            print(f"Error checking status for {tid}: {e}")
            status_counts["failed"] += 1
    
    return status_counts


async def run_load_test():
    """Run the complete load test."""
    print(f"Starting load test: sending {TOTAL_NOTIFICATIONS} notifications to {BASE_URL}")
    
    # Generate test data
    notifications = generate_test_notifications()
    print(f"Generated {len(notifications)} test notifications")
    
    # Send notifications
    start_time = time.time()
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # Test service availability
        try:
            health_resp = await client.get("/healthz")
            if health_resp.status_code != 200:
                print(f"Service health check failed: {health_resp.status_code}")
                return
        except Exception as e:
            print(f"Cannot connect to service at {BASE_URL}: {e}")
            return
        
        print("Service is healthy, starting load test...")
        
        # Send notifications in batches for better concurrency
        batch_size = 50
        all_tracking_ids = []
        
        for i in range(0, len(notifications), batch_size):
            batch = notifications[i:i + batch_size]
            batch_start = time.time()
            
            # Send batch concurrently
            tasks = []
            for notif in batch:
                task = client.post("/notifications/send", json=notif)
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process responses
            batch_tracking_ids = []
            for resp in responses:
                if isinstance(resp, Exception):
                    print(f"Request failed: {resp}")
                    continue
                
                if resp.status_code == 200:
                    data = resp.json()
                    batch_tracking_ids.append(data["tracking_id"])
                else:
                    print(f"Failed request: {resp.status_code}")
            
            all_tracking_ids.extend(batch_tracking_ids)
            batch_time = time.time() - batch_start
            print(f"Sent batch {i//batch_size + 1}/{(len(notifications) + batch_size - 1)//batch_size}: "
                  f"{len(batch_tracking_ids)}/{len(batch)} successful in {batch_time:.2f}s")
    
    send_time = time.time() - start_time
    send_rate = len(all_tracking_ids) / send_time if send_time > 0 else 0
    
    print(f"\nSending complete:")
    print(f"- Total sent: {len(all_tracking_ids)}/{TOTAL_NOTIFICATIONS}")
    print(f"- Send time: {send_time:.2f}s")
    print(f"- Send rate: {send_rate:.1f} notifications/second")
    
    if not all_tracking_ids:
        print("No notifications were sent successfully")
        return
    
    # Wait a bit for processing
    print("\nWaiting 10 seconds for processing...")
    await asyncio.sleep(10)
    
    # Check delivery status
    print("Checking delivery status...")
    status_start = time.time()
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        status_counts = await check_delivery_status(client, all_tracking_ids)
    
    status_time = time.time() - status_start
    total_time = time.time() - start_time
    
    print(f"\nLoad test results:")
    print(f"- Total time: {total_time:.2f}s")
    print(f"- Status check time: {status_time:.2f}s")
    print(f"- Overall rate: {len(all_tracking_ids) / total_time:.1f} notifications/second")
    print(f"\nDelivery status breakdown:")
    for status, count in status_counts.items():
        percentage = (count / len(all_tracking_ids)) * 100 if all_tracking_ids else 0
        print(f"- {status}: {count} ({percentage:.1f}%)")
    
    # Success criteria
    delivered_rate = status_counts.get("delivered", 0) / len(all_tracking_ids) if all_tracking_ids else 0
    success = (
        send_rate >= 50 and  # At least 50 notifications/second send rate
        delivered_rate >= 0.8  # At least 80% delivery rate
    )
    
    print(f"\nPerformance assessment:")
    print(f"- Send rate target (≥50/s): {'✓' if send_rate >= 50 else '✗'} ({send_rate:.1f}/s)")
    print(f"- Delivery rate target (≥80%): {'✓' if delivered_rate >= 0.8 else '✗'} ({delivered_rate*100:.1f}%)")
    print(f"- Overall: {'PASS' if success else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(run_load_test())
