#!/usr/bin/env python3

import argparse
import enum
import json
import threading
import time


import requests
import paho.mqtt.client as mqtt


class Keel:

    BASE = 'http://{host}:{port}/v1/{endpoint}'

    class Endpoint(enum.Enum):

        APPROVALS = 'approvals'

    def __init__(self, username: str, password: str, host: str, port: int):
        self.host = host
        self.port = port
        self.session = requests.Session()
        self.session.auth = (username, password)

    def pending_approvals(self):
        return self.session.get(
            self._endpoint(self.Endpoint.APPROVALS)
        ).json()

    def _endpoint(self, endpoint: Endpoint):
        return self.BASE.format(
            host=self.host,
            port=self.port,
            endpoint=endpoint.value,
        )


class FakeKeel(Keel):

    def __init__(self, *args):
        pass

    def pending_approvals(self):
        return [
            {
                "provider": "helm",
                "identifier": "default/wd:0.0.15",
                "event": {
                    "repository": {
                        "host": "",
                        "name": "index.docker.io/karolisr/webhook-demo",
                        "tag": "0.0.15",
                        "digest": ""
                    },
                    "createdAt": "0001-01-01T00:00:00Z",
                    "triggerName": "poll"
                },
                "message": "New image is available for release default/wd (0.0.13 -> 0.0.15).",
                "currentVersion": "0.0.13",
                "newVersion": "0.0.15",
                "votesRequired": 1,
                "deadline": "2017-09-26T09:14:54.979211563+01:00",
                "createdAt": "2017-09-26T09:14:54.980936804+01:00",
                "updatedAt": "2017-09-26T09:14:54.980936824+01:00"
            }
        ]


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--keel-service', default='keel')
    parser.add_argument('--keel-port', default=9300)
    parser.add_argument('--keel-username', required=True)
    parser.add_argument('--keel-password', required=True)
    parser.add_argument('--keel-poll-interval', default=60, type=int)
    parser.add_argument('--keel-stub', action='store_true')
    parser.add_argument('--mqtt-host', required=True)
    parser.add_argument('--mqtt-username')
    parser.add_argument('--mqtt-password')

    return parser.parse_args()


def poll_keel(poll_interval: int, keel_client: Keel, mqtt_client):
    while True:
        approvals = keel_client.pending_approvals()

        for approval in approvals:
            identifier, *_ = approval['identifier'].split(':')
            identifier = identifier.replace('/', '_')

            state_topic = f'keel/{identifier}'
            latest_version_topic = f'{state_topic}/latest'

            mqtt_client.publish(state_topic, json.dumps({
                'installed_version': approval['currentVersion'],
                'latest_version': approval['newVersion'],
                'title': identifier,
                'release_summary': approval['message'],
            }))
            mqtt_client.publish(latest_version_topic, json.dumps({'version': approval['newVersion']}))

            discovery_payload = {
                'command_topic': 'keel/approvals',
                'latest_version_template': '{{ value_json["version"] }}',
                'latest_version_topic': latest_version_topic,
                'name': identifier,
                'object_id': identifier,
                'origin': {
                    'name': 'keel-ha-bridge',
                    'sw_version': '1.0',
                    'support_url': 'https://github.com/craigcabrey/keel-ha-bridge',
                },
                'payload_install': identifier,
                'state_topic': state_topic,
                'unique_id': identifier,
            }

            mqtt_client.publish(f'homeassistant/update/{identifier}/config', json.dumps(discovery_payload))

        time.sleep(poll_interval)


# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe("$SYS/#")


# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    print(msg.topic+" "+str(msg.payload))


def init_mqqt(args):
    mqqt_client = mqtt.Client()
    mqqt_client.on_connect = on_connect
    mqqt_client.on_message = on_message

    mqqt_client.username_pw_set(args.mqtt_username, password=args.mqtt_password)
    mqqt_client.connect(args.mqtt_host, 1883, 60)

    mqqt_client.username_pw_set(args.mqtt_username, password=args.mqtt_password)
    mqqt_client.connect(args.mqtt_host, 1883, 60)

    mqqt_client.loop_start()

    return mqqt_client


def main():
    args = parse_args()

    mqqt_client = init_mqqt(args)

    if args.keel_stub:
        keel_client = FakeKeel()
    else:
        keel_client = Keel(args.keel_username, args.keel_password, args.keel_service, args.keel_port)

    keel_poll = threading.Thread(target=poll_keel, args=(args.keel_poll_interval, keel_client, mqqt_client))
    keel_poll.start()
    keel_poll.join()

    return True


if __name__ == '__main__':
    main()
