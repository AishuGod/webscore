import requests
import pika
from bs4 import BeautifulSoup
import time
import os
import multiprocessing
from urllib.parse import urljoin, urlparse, urldefrag

# --------------------------------------------------
# EXISTING FUNCTIONS (UNCHANGED)
# --------------------------------------------------

def fetch_page(url, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[INFO] Fetching (attempt {attempt}/{max_retries}): {url}")

            response = requests.get(
                url,
                timeout=5,
                headers={"User-Agent": "WebScourCrawler/1.0"}
            )

            if response.status_code == 200:
                return response.text
            else:
                print(f"[ERROR] Status {response.status_code} for {url}")
                return None

        except Exception as error:
            print(f"[ERROR] Problem while fetching {url}: {error}")

            if attempt == max_retries:
                print(f"[ERROR] Giving up on {url}")
                return None

            time.sleep(1)


def extract_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()

        if not href:
            continue
        if href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue

        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)

        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue

        links.add(absolute)

    return links

# --------------------------------------------------
# TASK 3 + TASK 4: WORKER LOGIC
# --------------------------------------------------

visited = set()

folder_name = "pages"
if not os.path.exists(folder_name):
    os.mkdir(folder_name)


def worker_function(worker_id):
    """
    Each process runs this function.
    worker_id helps identify which worker is crawling which URL.
    """

    def crawl_url_worker(ch, method, properties, body):
        url = body.decode() # Decode bytes to string
        print(f"[WORKER-{worker_id}] Crawling: {url}")

        if url in visited:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        html = fetch_page(url)
        if html is None:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        filename = os.path.join(folder_name, f"{hash(url)}.html")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"[WORKER-{worker_id}] Saved: {filename}")

        links = extract_links(html, url)
        seed_domain = urlparse(url).netloc

        for link in links:
            if urlparse(link).netloc == seed_domain:
                ch.basic_publish(
                    exchange="",
                    routing_key="url_queue",
                    body=link.encode()
                )

        visited.add(url)
        time.sleep(0.5)
        ch.basic_ack(delivery_tag=method.delivery_tag) # Acknowledge message processing complete

    connection = pika.BlockingConnection( # connect to RabbitMQ server
        pika.ConnectionParameters(host="localhost") # connect to RabbitMQ server
    )
    channel = connection.channel() # create a channel

    channel.queue_declare(queue="url_queue", durable=True) # declare a durable queue
    channel.basic_qos(prefetch_count=1) # fair dispatch

    channel.basic_consume( # consume messages from the queue
        queue="url_queue",
        on_message_callback=crawl_url_worker
    )

    print(f"[*] Worker-{worker_id} started. Waiting for URLs...")
    channel.start_consuming() # start consuming messages

# --------------------------------------------------
# PRODUCER (REAL WEBSITE SEEDING)
# --------------------------------------------------

def seed_urls():
    """
    Sends real website URLs to RabbitMQ.
    This simulates the URL Producer.
    """

    connection = pika.BlockingConnection( # connect to RabbitMQ server
        pika.ConnectionParameters(host="localhost") # specify host
    )
    channel = connection.channel() # create a channel

    channel.queue_declare(queue="url_queue", durable=True) # declare a durable queue

    seed_url = "https://en.wikipedia.org/wiki/Infosys" # real website URL

    channel.basic_publish( # publish the seed URL to the queue
        exchange="",
        routing_key="url_queue",
        body=seed_url.encode() # encode the URL to bytes for transmission via RabbitMQ
    )

    print(f"[PRODUCER] Seed URL sent: {seed_url}")
    connection.close()

# --------------------------------------------------
# TASK 4: MULTIPLE WORKER SIMULATION
# --------------------------------------------------

def main():
    """
    Starts multiple worker processes locally
    and seeds the queue with a real website.
    """

    # Step 1: Seed real website URL
    seed_urls()

    # Step 2: Start multiple workers
    NUM_WORKERS = 3
    processes = []

    for i in range(1, NUM_WORKERS + 1):
        p = multiprocessing.Process( # create a new process
            target=worker_function,
            args=(i,)
        )
        p.start() # start the process
        processes.append(p) # keep track of processes

    for p in processes: # wait for all processes to finish
        p.join()


if __name__ == "__main__":
    main()
