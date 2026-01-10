import pika
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import os
import time
import multiprocessing

# ================= Global Config =================
RABBITMQ_HOST = "localhost"
QUEUE_NAME = "url_queue"

NUM_WORKERS = 3
MAX_PAGES = 15

PAGES_FOLDER = "pages"
VISITED_FILE = "visited.txt"

# Shared variables across workers
visited = None
pages_fetched = None
page_counter = None
lock = None

# Ensure folder exists
os.makedirs(PAGES_FOLDER, exist_ok=True)

# ================= Worker Function =================
def process_url(ch, method, properties, body):
    global visited, pages_fetched, page_counter, lock

    url = body.decode()
    worker_name = multiprocessing.current_process().name.replace("Process", "WORKER")

    with lock:
        # Stop if max pages reached
        if pages_fetched.value >= MAX_PAGES:
            print(f"[{worker_name}] Max pages reached. Stopping.")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.stop_consuming()
            return

        # Skip if already visited
        if url in visited:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        visited.append(url)
        with open(VISITED_FILE, "a") as f:
            f.write(url + "\n")

        current_page = page_counter.value
        page_counter.value += 1
        pages_fetched.value += 1

    print(f"[{worker_name}] Crawling: {url}")

    try:
        response = requests.get(url, timeout=5)
        html = response.text

        # Save HTML
        filename = f"{PAGES_FOLDER}/page_{current_page}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[SAVED] {filename}")

        # Extract and enqueue links
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("a", href=True):
            link = urljoin(url, tag["href"])
            if urlparse(link).scheme.startswith("http"):
                with lock:
                    if pages_fetched.value < MAX_PAGES:
                        ch.basic_publish(
                            exchange="",
                            routing_key=QUEUE_NAME,
                            body=link,
                            properties=pika.BasicProperties(delivery_mode=2)
                        )

        print(f"[{worker_name}] ACK: {url}")

    except Exception as e:
        print(f"[{worker_name}] ERROR: {url} | {e}")

    ch.basic_ack(delivery_tag=method.delivery_tag)

# ================= Start Worker =================
def start_worker(worker_id, shared_visited, shared_pages, shared_counter, shared_lock):
    global visited, pages_fetched, page_counter, lock

    visited = shared_visited
    pages_fetched = shared_pages
    page_counter = shared_counter
    lock = shared_lock

    print(f"[WORKER-{worker_id}] Started")

    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=process_url)
    channel.start_consuming()

# ================= Main =================
if __name__ == "__main__":
    multiprocessing.freeze_support()

    print("Starting Distributed Web Crawler")
    print(f"Workers: {NUM_WORKERS}")

    start_time = time.time()

    # Shared memory for processes
    manager = multiprocessing.Manager()
    shared_visited = manager.list()
    shared_pages = manager.Value("i", 0)
    shared_counter = manager.Value("i", 1)
    shared_lock = manager.Lock()

    processes = []
    for i in range(NUM_WORKERS):
        p = multiprocessing.Process(
            target=start_worker,
            args=(i + 1, shared_visited, shared_pages, shared_counter, shared_lock)
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    end_time = time.time()

    print("\n========== SUMMARY ==========")
    print(f"Workers used      : {NUM_WORKERS}")
    print(f"Total pages crawled: {shared_pages.value}")
    print(f"Total time taken  : {round(end_time - start_time, 2)} sec")
