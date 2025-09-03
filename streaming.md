# Streaming Responses

> Learn how to stream real-time using Sonar

## Overview

Streaming allows you to receive partial responses from the Perplexity API as they are generated, rather than waiting for the complete response. This is particularly useful for:

* **Real-time user experiences** - Display responses as they're generated
* **Long responses** - Start showing content immediately for lengthy analyses
* **Interactive applications** - Provide immediate feedback to users

<Info>
  Streaming is supported across all Perplexity models including Sonar, Sonar Pro, and reasoning models.
</Info>

## Quick Start

To enable streaming, add `"stream": true` to your API request:

<Tabs>
  <Tab title="Requests (Python)">
    ```python
    import requests
    import json

    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sonar",
        "messages": [{"role": "user", "content": "What is the latest in AI research?"}],
        "stream": True
    }

    with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if raw_line.startswith("data: "):
                data_str = raw_line[len("data: ") :]
                if data_str == "[DONE]":
                    break
                chunk = json.loads(data_str)
                delta = chunk["choices"][0].get("delta", {})
                if (content := delta.get("content")):
                    print(content, end="")
    ```
  </Tab>

  <Tab title="Requests (TypeScript)">
    ```typescript
    const resp = await fetch("https://api.perplexity.ai/chat/completions", {
      method: "POST",
      headers: {
        Authorization: "Bearer YOUR_API_KEY",
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        model: "sonar",
        messages: [{ role: "user", content: "What is the latest in AI research?" }],
        stream: true,
      }),
    });

    if (!resp.body) throw new Error("No response body");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIndex;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const event = buffer.slice(0, sepIndex).trim();
        buffer = buffer.slice(sepIndex + 2);
        if (event.startsWith("data: ")) {
          const data = event.slice(6).trim();
          if (data === "[DONE]") break;
          const chunk = JSON.parse(data);
          const content = chunk.choices?.[0]?.delta?.content;
          if (content) {
            process.stdout.write(content);
          }
        }
      }
    }
    ```
  </Tab>

  <Tab title="OpenAI (Python)">
    ```python
    from openai import OpenAI

    client = OpenAI(
        api_key="YOUR_API_KEY",
        base_url="https://api.perplexity.ai"
    )

    stream = client.chat.completions.create(
        model="sonar",
        messages=[{"role": "user", "content": "What is the latest in AI research?"}],
        stream=True
    )

    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            print(chunk.choices[0].delta.content, end="")
    ```
  </Tab>

  <Tab title="OpenAI (TypeScript)">
    ```typescript
    import OpenAI from "openai";

    const client = new OpenAI({
      apiKey: "YOUR_API_KEY",
      baseURL: "https://api.perplexity.ai",
    });

    const stream = await client.chat.completions.create({
      model: "sonar",
      messages: [{ role: "user", content: "What is the latest in AI research?" }],
      stream: true,
    });

    for await (const chunk of stream) {
      const content = chunk.choices?.[0]?.delta?.content;
      if (content) process.stdout.write(content);
    }
    ```
  </Tab>
</Tabs>

### Basic Implementation

With this code snippet, you can stream responses from the Perplexity API using the requests library. However, you will need to parse the response manually to get the content, search results, and metadata.

```python
import requests

# Set up the API endpoint and headers
url = "https://api.perplexity.ai/chat/completions"
headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}

payload = {
    "model": "sonar-pro",
    "messages": [
        {"role": "user", "content": "Who are the top 5 tech influencers on X?"}
    ],
    "stream": True  # Enable streaming for real-time responses
}

response = requests.post(url, headers=headers, json=payload, stream=True)

# Process the streaming response (simplified example)
for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

### Streaming Best Practices

<Tabs>
  <Tab title="Gathering Search Results">
    Gather all your search results and metadata in the final chunk of the response neatly in an array.

    ```python
    from openai import OpenAI

    client = OpenAI(
        api_key="YOUR_API_KEY",
        base_url="https://api.perplexity.ai"
    )

    stream = client.chat.completions.create(
        model="sonar-pro",
        messages=[
            {"role": "user", "content": "Compare renewable energy technologies"}
        ],
        stream=True
    )

    content = ""
    search_results = []
    usage_info = None

    for chunk in stream:
        # Content arrives progressively
        if chunk.choices[0].delta.content is not None:
            content_chunk = chunk.choices[0].delta.content
            content += content_chunk
            print(content_chunk, end="")
        
        # Metadata arrives in final chunks
        if hasattr(chunk, 'search_results') and chunk.search_results:
                    search_results = chunk.search_results
        
        if hasattr(chunk, 'usage') and chunk.usage:
            usage_info = chunk.usage
        
        # Handle completion
        if chunk.choices[0].finish_reason is not None:
            print(f"\n\nFinish reason: {chunk.choices[0].finish_reason}")
            print(f"Search Results: {search_results}")
            print(f"Usage: {usage_info}")
    ```
  </Tab>

  <Tab title="Error handling">
    Error handling is important to ensure your application can recover from errors and provide a good user experience.

    <CodeGroup>
      ```python Retry with backoff
      import requests
      import time
      import json

      url = "https://api.perplexity.ai/chat/completions"
      headers = {
          "Authorization": "Bearer YOUR_API_KEY",
          "Content-Type": "application/json",
          "Accept": "application/json"
      }

      data = {
          "model": "sonar-pro",
          "messages": [
              {"role": "system", "content": "Be precise and concise."},
              {"role": "user", "content": "Explain machine learning concepts"}
          ],
          "stream": True,
          "max_tokens": 1000,
          "temperature": 0.2,
          "top_p": 0.9,
          "presence_penalty": 0,
          "frequency_penalty": 0,
          "extra": {
              "search_mode": "web",
              "reasoning_effort": "medium",
              "web_search_options": {
                  "search_context_size": "low"
              }
          }
      }

      def stream_with_retry(max_retries=3):
          for attempt in range(max_retries):
              try:
                  with requests.post(url, headers=headers, json=data, stream=True, timeout=300) as resp:
                      resp.raise_for_status()
                      for line in resp.iter_lines(decode_unicode=True):
                          if line and line.startswith("data: "):  # Per OpenAI/Perplexity streaming format
                              chunk = json.loads(line[len("data: "):])
                              content = chunk["choices"][0].get("delta", {}).get("content")
                              if content:
                                  print(content, end="", flush=True)
                  break
              except Exception as e:
                  print(f"Attempt {attempt + 1} failed: {e}")
                  if attempt < max_retries - 1:
                      time.sleep(2 ** attempt)

      stream_with_retry()
      ```

      ```python Exceptions and parsing
      import requests
      import json

      def stream_with_error_handling():
          url = "https://api.perplexity.ai/chat/completions"
          headers = {
              "Authorization": "Bearer YOUR_API_KEY",
              "Content-Type": "application/json"
          }
          payload = {
              "model": "sonar",
              "messages": [{"role": "user", "content": "Explain machine learning"}],
              "stream": True
          }
          
          try:
              response = requests.post(url, headers=headers, json=payload, stream=True)
              response.raise_for_status()
              
              for line in response.iter_lines():
                  if line:
                      line = line.decode('utf-8')
                      if line.startswith('data: '):
                          data_str = line[6:]
                          if data_str == '[DONE]':
                              break
                          try:
                              chunk_data = json.loads(data_str)
                              content = chunk_data['choices'][0]['delta'].get('content', '')
                              if content:
                                  print(content, end='')
                          except json.JSONDecodeError:
                              continue
                              
          except requests.exceptions.RequestException as e:
              print(f"Request failed: {e}")
          except Exception as e:
              print(f"Error: {e}")

      stream_with_error_handling()
      ```
    </CodeGroup>
  </Tab>

  <Tab title="Proper SSE Parsing">
    For production use, you should properly parse Server-Sent Events (SSE) format:

    ```python
    import requests
    import json

    def stream_with_proper_parsing():
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": "Bearer YOUR_API_KEY",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sonar",
            "messages": [{"role": "user", "content": "Explain quantum computing"}],
            "stream": True
        }
        
        response = requests.post(url, headers=headers, json=payload, stream=True)
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove 'data: ' prefix
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk_data = json.loads(data_str)
                        content = chunk_data['choices'][0]['delta'].get('content', '')
                        if content:
                            print(content, end='')
                    except json.JSONDecodeError:
                        continue

    stream_with_proper_parsing()
    ```
  </Tab>
</Tabs>

## Search Results and Metadata During Streaming

<Info>
  Search results and metadata are delivered in the **final chunk(s)** of a streaming response, not progressively during the stream.
</Info>

### How Metadata Works with Streaming

When streaming, you receive:

1. **Content chunks** which arrive progressively in real-time
2. **Search results** (delivered in the final chunk(s))
3. **Usage stats**

### Using Requests Library for Metadata

```python
import requests
import json

def stream_with_requests_metadata():
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sonar",
        "messages": [{"role": "user", "content": "Explain quantum computing"}],
        "stream": True
    }
    
    response = requests.post(url, headers=headers, json=payload, stream=True)
    
    content = ""
    metadata = {}
    
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data_str = line[6:]
                if data_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(data_str)
                    
                    # Process content
                    if 'choices' in chunk and chunk['choices'][0]['delta'].get('content'):
                        content_piece = chunk['choices'][0]['delta']['content']
                        content += content_piece
                        print(content_piece, end='', flush=True)
                    
                    # Collect metadata
                    for key in ['search_results', 'usage']:
                        if key in chunk:
                            metadata[key] = chunk[key]
                            
                    # Check if streaming is complete
                    if chunk['choices'][0].get('finish_reason'):
                        print(f"\n\nMetadata: {metadata}")
                        
                except json.JSONDecodeError:
                    continue
    
    return content, metadata

stream_with_requests_metadata()
```

<Warning>
  **Important**: If you need search results immediately for your user interface, consider using non-streaming requests for use cases where search result display is critical to the real-time user experience.
</Warning>
