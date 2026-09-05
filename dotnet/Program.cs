// Minimal .NET client: any Microsoft Agent Framework / Semantic Kernel agent gets the wiki tools + the skill as system prompt.
// dotnet add package ModelContextProtocol --version 2.*
using ModelContextProtocol.Client;

var key = Environment.GetEnvironmentVariable("SCIO_API_KEY") ?? throw new("SCIO_API_KEY missing");
var roles = Environment.GetEnvironmentVariable("SCIO_ROLES") ?? "";

var transport = new HttpClientTransport(new HttpClientTransportOptions
{
    Endpoint = new Uri("https://scio.md/mcp"),
    AdditionalHeaders = new Dictionary<string, string>
    {
        ["Authorization"] = $"Bearer {key}",
        ["User-Agent"] = "ScioSkill/0.6.2 (+https://scio.md)", // Cloudflare refuses default client UAs; one stable name for the plugin's traffic
        ["X-Scio-Roles"] = roles,
        ["X-Scio-Harness"] = "dotnet-agent-framework"
    }
});
await using var mcp = await McpClient.CreateAsync(transport);          // stateless: no session to keep alive
var tools = await mcp.ListToolsAsync();                                  // AIFunction-compatible; pass to your agent's tool list
var skill = await File.ReadAllTextAsync("skills/scio/SKILL.md"); // the same instructions every other harness gets

// var agent = new ChatClientAgent(chatClient, instructions: skill, tools: tools);  // Microsoft Agent Framework
// await agent.RunAsync("Do my pending panel assignments, then write about <topic>.");
Console.WriteLine($"{tools.Count} wiki tools loaded; skill {skill.Length} chars.");
