from datasette import hookimpl, Response
import openai

CHAT = """
<!DOCTYPE html>
<html>
<head>
    <title>WebSocket Client</title>
</head>
<body>
    <h1>WebSocket Client</h1>
    <textarea id="message" rows="4" cols="50"></textarea><br>
    <button onclick="sendMessage()">Send Message</button>
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
            console.log({message, ws});
            ws.send(message);
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

            async for chunk in await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "user",
                        "content": message,
                    }
                ],
                stream=True,
            ):
                content = chunk["choices"][0].get("delta", {}).get("content")
                if content is not None:
                    await send({"type": "websocket.send", "text": content})

        elif event["type"] == "websocket.disconnect":
            break


def chat():
    return Response.html(CHAT)


@hookimpl
def register_routes():
    return [
        (r"^/ws$", websocket_application),
        (r"^/chat$", chat),
    ]
