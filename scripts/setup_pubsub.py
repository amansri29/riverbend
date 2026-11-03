"""Create the topic, push subscription, dead-letter topic and its subscription.
Works against the emulator (PUBSUB_EMULATOR_HOST set) and against real Pub/Sub."""

from __future__ import annotations

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1
from google.protobuf.duration_pb2 import Duration
from google.pubsub_v1.types import DeadLetterPolicy, PushConfig, RetryPolicy

from app.config import get_settings


def main() -> None:
    s = get_settings()
    pub = pubsub_v1.PublisherClient()
    sub = pubsub_v1.SubscriberClient()
    topic = pub.topic_path(s.pubsub_project, s.pubsub_topic)
    dlq_topic = pub.topic_path(s.pubsub_project, s.pubsub_dlq_topic)
    for t in (topic, dlq_topic):
        try:
            pub.create_topic(name=t)
            print("created topic", t)
        except AlreadyExists:
            print("topic exists", t)

    main_sub = sub.subscription_path(s.pubsub_project, s.pubsub_subscription)
    try:
        sub.create_subscription(
            request={
                "name": main_sub,
                "topic": topic,
                "push_config": PushConfig(push_endpoint=s.pubsub_push_endpoint),
                "ack_deadline_seconds": 120,
                "retry_policy": RetryPolicy(
                    minimum_backoff=Duration(seconds=10), maximum_backoff=Duration(seconds=600)
                ),
                "dead_letter_policy": DeadLetterPolicy(dead_letter_topic=dlq_topic, max_delivery_attempts=5),
            }
        )
        print("created subscription", main_sub)
    except AlreadyExists:
        print("subscription exists", main_sub)

    dlq_sub = sub.subscription_path(s.pubsub_project, s.pubsub_dlq_subscription)
    try:
        sub.create_subscription(
            request={
                "name": dlq_sub,
                "topic": dlq_topic,
                "push_config": PushConfig(push_endpoint=s.pubsub_dlq_push_endpoint),
                "ack_deadline_seconds": 60,
            }
        )
        print("created subscription", dlq_sub)
    except AlreadyExists:
        print("subscription exists", dlq_sub)


if __name__ == "__main__":
    main()
