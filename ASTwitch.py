#!/usr/bin/python3
# ASTwitch

import ewmh, aiohttp, asyncio, twitchio
from twitchio.ext import commands, eventsub
from utils import *; logstart('ASTwitch')

from config import TOKEN, WS2LP_BASE_URL

categories = Sdict(str)  # {id: name}
stats = Sdict(lambda: Sdict(int))  # {id: {window: ticks}}
db.setfile('ASTwitch.db')
db.setbackup(False)
db.register('categories', 'stats')

class LongpolledEvent(eventsub.BaseEvent):
	def __init__(self, client: eventsub.EventSubClient, data: str):
		self._client = client
		self._raw_data = data
		_data: dict = _loads(data)
		self.subscription = eventsub.Subscription(_data["subscription"])
		self.setup(_data)
class LongpolledNotificationEvent(eventsub.NotificationEvent, LongpolledEvent): pass
class LongpolledRevocationEvent(eventsub.NotificationEvent, LongpolledEvent): pass

async def run_longpoll(client):
	await client.wait_for_ready()

	async with aiohttp.ClientSession() as s:
		async with s.post(f"{WS2LP_BASE_URL}/create", params={'response': '.challenge'}) as r:
			data = await r.json()

		try:
			hash, secret = data['hash'], data['secret']
			webhook_url = f"{WS2LP_BASE_URL}/wh/{hash}"
			longpoll_url = f"{WS2LP_BASE_URL}/lp/{hash}?secret={secret}"

			channel_id = client.user_id

			eventsub_client = eventsub.EventSubClient(client, 's3cRe7', callback_route=webhook_url)
			await eventsub_client.subscribe_channel_stream_start(channel_id)
			await eventsub_client.subscribe_channel_stream_end(channel_id)
			await eventsub_client.subscribe_channel_update(channel_id)

			while (True):
				async with s.get(longpoll_url) as r:
					data = await r.json()
					body = data['body']
					if (body['subscription']['status'] in ('user_removed', 'authorization_revoked', 'notification_failures_exceeded')):
						event = LongpolledRevocationEvent(eventsub_client, body)
						self.client.run_event('eventsub_revocation', event)
					else:
						event = LongpolledNotificationEvent(eventsub_client, body)
						self.client.run_event(f"eventsub_notification_{eventsub.SubscriptionTypes._name_map[event.subscription.type]}", event)
		finally: await s.post(f"{WS2LP_BASE_URL}/delete", params=data)

worker_task = None
worker_category = None

async def worker(client):
	await client.wait_for_ready()
	log("Worker task started")
	channel_id = client.user_id

	wm = ewmh.EWMH()

	while (True):
		await asyncio.sleep(1)
		if (worker_category is None): continue

		win = wm.getActiveWindow()
		if (win is not None): cat = win.get_wm_class()
		else: cat = None

		stats[worker_category][cat] += 1

async def eventsub_notification_stream_start(payload: eventsub.StreamOnlineData):
	global worker_task
	worker_task = asyncio.create_task(worker(payload.broadcaster.id))

async def eventsub_notification_stream_end(payload: eventsub.StreamOfflineData):
	global worker_task
	if (worker_task is not None):
		worker_task.cancel()
		await worker_task
		worker_task = None

async def eventsub_notification_channel_update(payload: eventsub.ChannelUpdateData):
	global worker_category
	worker_category = payload.category_id
	categories[payload.category_id] = payload.category_name
	dlog(payload.category_name)

def main():
	global worker_task

	db.load()

	client = twitchio.Client(token=TOKEN)

	client.event()(eventsub_notification_stream_start)
	client.event()(eventsub_notification_stream_end)
	client.event()(eventsub_notification_channel_update)

	client.loop.create_task(run_longpoll(client))
	client.loop.create_task(client.start())
	worker_task = client.loop.create_task(worker(client)) # TODO FIXME: check if stream is running

	try: client.loop.run_forever()
	except KeyboardInterrupt as ex: exit(ex)

if (__name__ == '__main__'): logstarted(); exit(main())
else: logimported()

# by Sdore, 2022
#  www.sdore.me
