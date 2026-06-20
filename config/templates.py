TEMPLATE_LIST = [
    {
        "key": "free-talk",
        "name": "Free Talk",
        "description": "A plain text conversation with the model.",
        "modulePath": "",
        "isStartBackground": False,
        "isUserMessageAccepted": True,
        "metadataCreate": {
            "statusText": "active",
            "isUserTurn": True,
        },
        "metadataStartFinish": {
            "statusText": "active",
            "isUserTurn": True,
        },
    },
    {
        "key": "web-fetch-local",
        "name": "Web Fetch Local",
        "description": "Fetches live web page text and asks the model to answer from the fetched text.",
        "modulePath": "test/_0_web_fetch_local/orchestrator.py",
        "isStartBackground": False,
        "isUserMessageAccepted": True,
        "metadataCreate": {
            "statusText": "active",
            "isUserTurn": True,
        },
        "metadataStartFinish": {
            "statusText": "active",
            "isUserTurn": True,
        },
    },
    {
        "key": "mcp-tool-all",
        "name": "MCP Tool Exercise",
        "description": "Asks the agent to try every available tool and lets the orchestrator handle tool results.",
        "modulePath": "test/_1_mcp/orchestrator.py",
        "isStartBackground": True,
        "isUserMessageAccepted": False,
        "metadataCreate": {
            "statusText": "starting",
            "isUserTurn": False,
        },
        "metadataStartFinish": {
            "statusText": "completed",
            "isUserTurn": False,
            "endStatusText": "completed",
        },
    },
    {
        "key": "mcp-interactive",
        "name": "MCP Tool Exercise(Interactive)",
        "description": "Runs the MCP tool exercise first, then lets the user continue talking with tool support.",
        "modulePath": "test/_1_mcp/orchestrator.py",
        "isStartBackground": True,
        "isUserMessageAccepted": True,
        "metadataCreate": {
            "statusText": "starting",
            "isUserTurn": False,
        },
        "metadataStartFinish": {
            "statusText": "active",
            "isUserTurn": True,
        },
    },
    {
        "key": "subagent-test",
        "name": "Subagent Test",
        "description": "Launches one child subagent that returns a short text answer to the parent.",
        "modulePath": "test/_2_sub_agent/orchestrator_parent.py",
        "isStartBackground": False,
        "isStartTask": True,
        "isUserMessageAccepted": True,
        "metadataCreate": {
            "statusText": "active",
            "isUserTurn": False,
        },
        "metadataStartFinish": {
            "statusText": "active",
            "isUserTurn": True,
        },
    },
    {
        "key": "subagent-basic",
        "name": "Subagent Basic",
        "description": "Internal subagent template for backend subagent tool calls.",
        "modulePath": "test/_2_sub_agent/orchestrator_subagent.py",
        "isStartBackground": False,
        "isUserMessageAccepted": False,
        "isInternal": True,
        "metadataCreate": {
            "statusText": "active",
            "isUserTurn": False,
        },
        "metadataStartFinish": {
            "statusText": "completed",
            "isUserTurn": False,
            "endStatusText": "completed",
        },
    },
]
