import asyncio
from concurrent.futures import ThreadPoolExecutor
from datasette import hookimpl, Response
import json
import llm

END_SIGNAL = object()


def async_wrap(generator_func, *args, **kwargs):
    def next_item(gen):
        try:
            return next(gen)
        except StopIteration:
            return END_SIGNAL

    async def async_generator():
        loop = asyncio.get_running_loop()
        generator = iter(generator_func(*args, **kwargs))
        with ThreadPoolExecutor() as executor:
            while True:
                item = await loop.run_in_executor(executor, next_item, generator)
                if item is END_SIGNAL:
                    break
                yield item

    return async_generator


CHAT = """
<!DOCTYPE html>
<html>
<head>
    <title>WebSocket Client</title>
</head>
<body>
    <h1>WebSocket Client</h1>
    <p><label>Model</label> <select id="model">OPTIONS</select></p>
    <textarea id="message" rows="4" cols="50"></textarea><br>
    <button onclick="sendMessage()">Send Message</button> <button onclick="clearLog()">Clear</button>
    <div id="log" style="margin-top: 1em; white-space: pre-wrap;"></div>

    <script>
        const ws = new WebSocket(`ws://${location.host}/ws`);

        ws.onmessage = function(event) {
            console.log(event);
            const log = document.getElementById('log');
            log.textContent += event.data;
        };

        function sendMessage() {
            const message = document.getElementById('message').value;
            const model = document.getElementById('model').value;
            console.log({message, model, ws});
            ws.send(JSON.stringify({message, model}));
        }

        function clearLog() {
            const log = document.getElementById('log');
            log.textContent = '';
        }
    </script>
</body>
</html>
""".strip()


async def websocket_application(scope, receive, send):
    if scope["type"] != "websocket":
        return Response.text("ws only", status=400)
    while True:
        event = await receive()
        if event["type"] == "websocket.connect":
            await send({"type": "websocket.accept"})
        elif event["type"] == "websocket.receive":
            message = event["text"]
            # {"message":"...","model":"gpt-3.5-turbo"}
            decoded = json.loads(message)
            model_id = decoded["model"]
            message = decoded["message"]
            model = llm.get_model(model_id)
            async for chunk in async_wrap(model.prompt, message)():
                await send({"type": "websocket.send", "text": chunk})
            await send({"type": "websocket.send", "text": "\n\n"})

        elif event["type"] == "websocket.disconnect":
            break


def chat():
    return Response.html(
        CHAT.replace(
            "OPTIONS",
            "\n".join(
                '<option value="{model}">{name}</option>'.format(
                    model=model_with_alias.model.model_id,
                    name=str(model_with_alias.model),
                )
                for model_with_alias in llm.get_models_with_aliases()
            ),
        )
    )


@hookimpl
def register_routes():
    return [
        (r"^/ws$", websocket_application),
        (r"^/chat$", chat),
    ]
