#!/usr/bin/env python3
"""
Example: Using DirectCodeConverter with Manual Input

This demonstrates how to use the DirectCodeConverter to transform
simplified shape JSON into complete tldraw snapshots.
"""

import json
from direct_code_converter import DirectCodeConverter


def example_authentication_flow():
    """Example: User authentication flow diagram."""
    print("=" * 60)
    print("Example: User Authentication Flow")
    print("=" * 60)

    # Simplified JSON (what an LLM might generate)
    simplified = {
        "shapes": [
            # User node
            {
                "id": "user",
                "type": "geo",
                "x": 100,
                "y": 150,
                "props": {
                    "text": "User",
                    "geo": "ellipse",
                    "color": "blue",
                    "w": 120,
                    "h": 60
                }
            },
            # Login form node
            {
                "id": "login_form",
                "type": "geo",
                "x": 300,
                "y": 150,
                "props": {
                    "text": "Login Form",
                    "geo": "rectangle",
                    "color": "violet",
                    "w": 140,
                    "h": 60
                }
            },
            # Auth service node
            {
                "id": "auth_service",
                "type": "geo",
                "x": 500,
                "y": 150,
                "props": {
                    "text": "Auth Service",
                    "geo": "rectangle",
                    "color": "green",
                    "w": 140,
                    "h": 60
                }
            },
            # Database node
            {
                "id": "database",
                "type": "geo",
                "x": 700,
                "y": 150,
                "props": {
                    "text": "Database",
                    "geo": "diamond",
                    "color": "orange",
                    "w": 140,
                    "h": 80
                }
            },
            # Arrow: User -> Login Form
            {
                "id": "arrow_user_form",
                "type": "arrow",
                "x": 220,
                "y": 180,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 80, "y": 0},
                    "text": "submit credentials"
                }
            },
            # Arrow: Login Form -> Auth Service
            {
                "id": "arrow_form_auth",
                "type": "arrow",
                "x": 440,
                "y": 180,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 60, "y": 0},
                    "text": "validate"
                }
            },
            # Arrow: Auth Service -> Database
            {
                "id": "arrow_auth_db",
                "type": "arrow",
                "x": 640,
                "y": 180,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 60, "y": 0},
                    "text": "query user"
                }
            },
            # Arrow: Database -> Auth Service (return)
            {
                "id": "arrow_db_auth",
                "type": "arrow",
                "x": 640,
                "y": 200,
                "props": {
                    "start": {"x": 60, "y": 0},
                    "end": {"x": 0, "y": 0},
                    "text": "user data",
                    "arrowheadStart": "arrow",
                    "arrowheadEnd": "none"
                }
            }
        ]
    }

    print("\nSimplified Input:")
    print(f"  - {len(simplified['shapes'])} shapes")
    print(f"  - 4 nodes (geo shapes)")
    print(f"  - 4 connections (arrows)")

    # Convert to complete tldraw snapshot
    converter = DirectCodeConverter()
    complete = converter.convert(simplified)

    # Save output
    output_path = "output/example_auth_flow.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(complete, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Complete snapshot saved to: {output_path}")
    print(f"  - Total objects in store: {len(complete['document']['store'])}")
    print(f"  - Can be rendered with tldraw render service")

    return complete


def example_system_architecture():
    """Example: Simple system architecture diagram."""
    print("\n" + "=" * 60)
    print("Example: System Architecture")
    print("=" * 60)

    simplified = {
        "shapes": [
            # Frontend
            {
                "id": "frontend",
                "type": "geo",
                "x": 150,
                "y": 100,
                "props": {
                    "text": "Frontend\n(React)",
                    "geo": "rectangle",
                    "color": "light-blue",
                    "fill": "semi"
                }
            },
            # API Gateway
            {
                "id": "api_gateway",
                "type": "geo",
                "x": 150,
                "y": 250,
                "props": {
                    "text": "API Gateway",
                    "geo": "rectangle",
                    "color": "violet"
                }
            },
            # Microservice 1
            {
                "id": "service1",
                "type": "geo",
                "x": 50,
                "y": 400,
                "props": {
                    "text": "User Service",
                    "geo": "cloud",
                    "color": "green"
                }
            },
            # Microservice 2
            {
                "id": "service2",
                "type": "geo",
                "x": 250,
                "y": 400,
                "props": {
                    "text": "Order Service",
                    "geo": "cloud",
                    "color": "green"
                }
            },
            # Arrow: Frontend -> Gateway
            {
                "id": "arrow1",
                "type": "arrow",
                "x": 220,
                "y": 160,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 90},
                    "text": "HTTP/REST"
                }
            },
            # Arrow: Gateway -> Service 1
            {
                "id": "arrow2",
                "type": "arrow",
                "x": 120,
                "y": 310,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": -20, "y": 90},
                    "text": "gRPC"
                }
            },
            # Arrow: Gateway -> Service 2
            {
                "id": "arrow3",
                "type": "arrow",
                "x": 220,
                "y": 310,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 100, "y": 90},
                    "text": "gRPC"
                }
            }
        ]
    }

    print("\nSimplified Input:")
    print(f"  - {len(simplified['shapes'])} shapes")
    print(f"  - Different shape types: rectangle, cloud")
    print(f"  - Different colors and fills")

    converter = DirectCodeConverter()
    complete = converter.convert(simplified)

    output_path = "output/example_system_arch.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(complete, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Complete snapshot saved to: {output_path}")

    return complete


if __name__ == "__main__":
    print("\nDirectCodeConverter Examples\n")

    # Run examples
    example_authentication_flow()
    example_system_architecture()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)
    print("\nTo render these diagrams:")
    print("  1. Start render service: cd evo_diagram/agentic_system/tool_services && npm run dev")
    print("  2. Use render_manifest_via_cli() to convert JSON to PNG")
    print("\nGenerated files:")
    print("  - output/example_auth_flow.json")
    print("  - output/example_system_arch.json")
