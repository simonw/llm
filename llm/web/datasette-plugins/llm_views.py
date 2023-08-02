import asyncio
from concurrent.futures import ThreadPoolExecutor
from datasette import hookimpl, Response
import json
import llm
from sqlite_utils import Database

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
                try:
                    item = await loop.run_in_executor(executor, next_item, generator)
                    if item is END_SIGNAL:
                        break
                    yield {"item": item}
                except Exception as ex:
                    yield {"error": str(ex)}
                    break

    return async_generator


CHAT = """
<!DOCTYPE html>
<html>
<head>
    <title>WebSocket Client</title>
</head>
<body>
    <h1>WebSocket Client</h1>
    <p><label for="model">Model</label> <select id="model">OPTIONS</select></p>
    <p><label for="system_prompt">System prompt</label></p>
    <p><textarea id="system_prompt" rows="2" cols="50"></textarea></p>
    <p><label for="message">Message</label></p>
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
            const system = document.getElementById('system_prompt').value;
            console.log({message, model, ws});
            ws.send(JSON.stringify({message, system, model}));
        }

        function clearLog() {
            const log = document.getElementById('log');
            log.textContent = '';
        }
    </script>
</body>
</html>
""".strip()


async def websocket_application(scope, receive, send, datasette):
    if scope["type"] != "websocket":
        return Response.text("ws only", status=400)

    db = datasette.get_database("logs")

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
            system = decoded["system"]
            model = llm.get_model(model_id)
            if model.needs_key:
                model.key = llm.get_key(None, model.needs_key, model.key_env_var)

            def run_in_thread(message):
                response = model.prompt(message, system=system)
                for chunk in response:
                    yield chunk
                yield {"end": response}

            async for item in async_wrap(run_in_thread, message)():
                if "error" in item:
                    await send({"type": "websocket.send", "text": item["error"]})
                else:
                    # It might be the 'end'
                    if isinstance(item["item"], dict) and "end" in item["item"]:
                        # Log to the DB
                        response = item["item"]["end"]
                        await db.execute_write_fn(
                            lambda conn: response.log_to_db(Database(conn)), block=False
                        )
                    else:
                        # Send the message to the client
                        await send({"type": "websocket.send", "text": item["item"]})
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
