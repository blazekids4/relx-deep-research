"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Send, Search, ExternalLink, FileText, Globe } from "lucide-react"
import { marked } from "marked"

interface Citation {
  id: string
  title: string
  source: string
  type: "licensed" | "web"
  url?: string
  snippet: string
}

interface Message {
  id: string
  type: "user" | "assistant"
  content: string
  citations?: Citation[]
  timestamp: Date
}

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollAreaRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    marked.setOptions({
      breaks: true,
      gfm: true,
    })
  }, [])

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      type: "user",
      content: input,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    try {
      // Replace with your FastAPI endpoint
      const response = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: input }),
      })

      if (!response.ok) {
        throw new Error("Search request failed")
      }

      const data = await response.json()

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: "assistant",
        content: data.answer || "I found some relevant information for your query.",
        citations: data.citations || [],
        timestamp: new Date(),
      }

      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      console.error("Search error:", error)

      // Mock response for demo purposes
      const mockCitations: Citation[] = [
        {
          id: "1",
          title: "Market Research Trends 2024",
          source: "Research Publisher",
          type: "licensed",
          snippet: "Key insights into emerging market trends and consumer behavior patterns...",
        },
        {
          id: "2",
          title: "Industry Analysis Report",
          source: "Web Source",
          type: "web",
          url: "https://example.com/report",
          snippet: "Comprehensive analysis of industry developments and competitive landscape...",
        },
      ]

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: "assistant",
        content:
          "Based on your query, I found relevant information from both our licensed content and web sources. The research indicates several key trends in the market, including emerging consumer preferences and technological developments that are reshaping the industry landscape.",
        citations: mockCitations,
        timestamp: new Date(),
      }

      setMessages((prev) => [...prev, assistantMessage])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="h-[600px] flex flex-col">
      <div className="p-4 border-b">
        <div className="flex items-center gap-2">
          <Search className="h-5 w-5 text-muted-foreground" />
          <span className="font-medium">Research Assistant</span>
        </div>
      </div>

      <ScrollArea className="flex-1 p-4" ref={scrollAreaRef}>
        <div className="space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground py-8">
              <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg mb-2">Start your research conversation</p>
              <p className="text-sm">Ask questions and get answers with citations from licensed and web sources</p>
            </div>
          )}

          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.type === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-lg p-3 ${
                  message.type === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                }`}
              >
                {message.type === "assistant" ? (
                  <div
                    className="text-sm leading-relaxed prose prose-sm max-w-none dark:prose-invert prose-p:my-2 prose-headings:my-2"
                    dangerouslySetInnerHTML={{ __html: marked(message.content) }}
                  />
                ) : (
                  <p className="text-sm leading-relaxed">{message.content}</p>
                )}

                {message.citations && message.citations.length > 0 && (
                  <div className="mt-3 space-y-2">
                    <p className="text-xs font-medium opacity-75">Sources:</p>
                    {message.citations.map((citation) => (
                      <div key={citation.id} className="bg-background/50 rounded p-2 text-xs">
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <div className="flex items-center gap-2">
                            {citation.type === "licensed" ? (
                              <FileText className="h-3 w-3" />
                            ) : (
                              <Globe className="h-3 w-3" />
                            )}
                            <span className="font-medium">{citation.title}</span>
                          </div>
                          <Badge variant={citation.type === "licensed" ? "default" : "secondary"} className="text-xs">
                            {citation.type === "licensed" ? "Licensed" : "Web"}
                          </Badge>
                        </div>
                        <p className="text-muted-foreground mb-1">{citation.source}</p>
                        <p className="text-foreground/80">{citation.snippet}</p>
                        {citation.url && (
                          <a
                            href={citation.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-primary hover:underline mt-1"
                          >
                            <ExternalLink className="h-3 w-3" />
                            View source
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                <p className="text-xs opacity-50 mt-2">{message.timestamp.toLocaleTimeString()}</p>
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-muted rounded-lg p-3 max-w-[80%]">
                <div className="flex items-center gap-2">
                  <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full"></div>
                  <span className="text-sm">Searching across licensed and web sources...</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      <div className="p-4 border-t">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a research question..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button type="submit" disabled={isLoading || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </Card>
  )
}
