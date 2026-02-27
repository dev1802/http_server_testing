Created a HTTP server using FASTAPI
server is running on PORT 5050
Its able to handle both cases when backend is configured and when not.
It also handles streaming and non-streaming data.

Test command:
curl -X POST http://0.0.0.0:5050/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello AI"}], "stream": false}'
