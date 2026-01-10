import pika

connection = pika.BlockingConnection(
    pika.ConnectionParameters('localhost')
)
channel = connection.channel()

channel.queue_declare(queue='url_queue', durable=True)

seed_url = "https://www.python.org/"
channel.basic_publish(
    exchange='',
    routing_key='url_queue',
    body=seed_url
)

print("Sent seed URL:", seed_url)

connection.close()
