import { type NextRequest, NextResponse } from "next/server"

export async function POST(request: NextRequest) {
  try {
    const { query } = await request.json()

    // Replace this URL with your actual FastAPI backend endpoint
    const fastApiUrl = process.env.FASTAPI_URL || "http://localhost:8000"

    const response = await fetch(`${fastApiUrl}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query }),
    })

    if (!response.ok) {
      throw new Error(`FastAPI request failed: ${response.status}`)
    }

    const data = await response.json()

    return NextResponse.json(data)
  } catch (error) {
    console.error("API route error:", error)

    // Return error response
    return NextResponse.json({ error: "Search request failed" }, { status: 500 })
  }
}
