# Basic .NET Agent

This is a minimal .NET console app that creates a Microsoft Agent Framework agent using the Azure OpenAI Responses API with keyless authentication.

## Setup

The app loads Azure OpenAI settings from the workspace `.env` file:

```powershell
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.4
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_TENANT_ID=your-tenant-id
```

Authenticate with Azure before running:

```powershell
az login
```

`DefaultAzureCredential` is used to request an Entra token for `https://ai.azure.com/.default`, so Visual Studio, Azure CLI, managed identity, and other supported Azure Identity credentials can provide the token. The signed-in identity needs access to the Azure OpenAI resource.

## Run

Use the default prompt:

```powershell
dotnet run
```

Or pass your own prompt:

```powershell
dotnet run -- "Explain dependency injection in C# in two paragraphs."
```