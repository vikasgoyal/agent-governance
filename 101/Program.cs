using Azure.Core;using Azure.Identity;using Microsoft.Agents.AI;using Microsoft.Extensions.AI;using OpenAI;using OpenAI.Responses;using System.ComponentModel;using System.ClientModel;
using AgentGovernance;using AgentGovernance.Extensions.Microsoft.Agents;

LoadDotEnv();

string? endpoint = Environment.GetEnvironmentVariable("AZURE_OPENAI_ENDPOINT");

if (string.IsNullOrWhiteSpace(endpoint))
{
	Console.Error.WriteLine("Set AZURE_OPENAI_ENDPOINT in the environment or workspace .env file before running this agent.");
	return 1;
}

string deploymentName = Environment.GetEnvironmentVariable("AZURE_OPENAI_DEPLOYMENT_NAME") ?? "gpt-5.4-mini";
string? tenantId = Environment.GetEnvironmentVariable("AZURE_TENANT_ID");
string prompt = args.Length > 0
	? string.Join(' ', args)
	: "tell me weather in Seattle today.";

DefaultAzureCredential credential = new(new DefaultAzureCredentialOptions
{
	TenantId = tenantId
});
AccessToken token = await credential.GetTokenAsync(
	new TokenRequestContext(["https://ai.azure.com/.default"]));

OpenAIClient client = new(
	new ApiKeyCredential(token.Token),
	new OpenAIClientOptions
	{
		Endpoint = new Uri($"{endpoint.TrimEnd('/')}/openai/v1/")
	});

var kernel = new GovernanceKernel(new GovernanceOptions
{
    PolicyPaths = new() { "policies/maf.yaml" },
    EnablePromptInjectionDetection = true,
});


AIAgent agent = client
	.GetResponsesClient()
	.AsAIAgent(
		model: deploymentName,
		instructions: "You are a helpful coding assistant. Keep answers concise and practical.",
		name: "CodeHelper",
		tools: [AIFunctionFactory.Create(GetWeather)]);


var governedAgent = agent.WithGovernance(
    kernel,
    new AgentFrameworkGovernanceOptions
    {
        DefaultAgentId = "did:agentmesh:payments-agent",
        EnableFunctionMiddleware = true,
    });

for (int i = 0; i < 10; i++)
{
    Console.WriteLine($"Call {i + 1}:");
    Console.WriteLine(await governedAgent.RunAsync(prompt));
}
return 0;

[Description("Get the current weather for a city.")]
string GetWeather([Description("The city to get weather for.")] string city)
{
	var decision = kernel.EvaluateToolCall(
		"did:agentmesh:payments-agent",
		nameof(GetWeather),
		new() { ["city"] = city });

	if (!decision.Allowed)
	{
		Console.WriteLine($"\u001b[31m[Blocked by governance policy: {decision.Reason}]\u001b[0m\n");
		return $"Blocked by governance policy.";
	}


    return city.Trim().ToLowerInvariant() switch
	{
		"seattle" => "The weather in Seattle is 58 F and cloudy with light rain.",
		"london" => "The weather in London is 12 C and overcast.",
		"new york" or "new york city" => "The weather in New York is 64 F and partly cloudy.",
		"paris" => "The weather in Paris is 16 C and clear.",
		_ => $"The weather in {city} is 21 C and sunny."
	};
}

static void LoadDotEnv()
{
	string? envPath = FindFileInParents(Environment.CurrentDirectory, ".env")
		?? FindFileInParents(AppContext.BaseDirectory, ".env");

	if (envPath is null)
	{
		return;
	}

	foreach (string line in File.ReadAllLines(envPath))
	{
		string trimmedLine = line.Trim();

		if (string.IsNullOrWhiteSpace(trimmedLine) || trimmedLine.StartsWith('#'))
		{
			continue;
		}

		int separatorIndex = trimmedLine.IndexOf('=');

		if (separatorIndex <= 0)
		{
			continue;
		}

		string key = trimmedLine[..separatorIndex].Trim();
		string value = trimmedLine[(separatorIndex + 1)..].Trim().Trim('"');

		if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(key)))
		{
			Environment.SetEnvironmentVariable(key, value);
		}
	}
}

static string? FindFileInParents(string startPath, string fileName)
{
	DirectoryInfo? directory = new(startPath);

	while (directory is not null)
	{
		string candidatePath = Path.Combine(directory.FullName, fileName);

		if (File.Exists(candidatePath))
		{
			return candidatePath;
		}

		directory = directory.Parent;
	}

	return null;
}
