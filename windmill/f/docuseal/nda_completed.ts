// DocuSeal NDA Completion Webhook Handler
// BUG 12 FIX: Migrated from f/wiseagent/credentials to f/switchboard/wiseagent_oauth
// to eliminate dual-resource token conflict. Both resources shared the same OAuth app,
// causing whichever refreshed last to invalidate the other's refresh token.
//
// Now uses the same resource and refresh pattern as the lead intake pipeline.

import * as wmill from "windmill-client";

type DocuSealWebhook = {
  event_type: string;
  timestamp: string;
  data: {
    id: number;
    source: string;
    submitters: Array<{
      id: number;
      email: string;
      name: string;
      completed_at: string;
      values: Record<string, any>;
      documents: Array<{
        name: string;
        url: string;
      }>;
    }>;
    template: {
      id: number;
      name: string;
    };
  };
};

type WiseAgentOAuth = {
  client_id: string;
  client_secret: string;
  access_token: string;
  refresh_token: string;
  expires_at: string;
};

async function refreshTokenIfNeeded(oauth: WiseAgentOAuth): Promise<string> {
  const expiresAt = new Date(oauth.expires_at);
  const now = new Date();

  if (expiresAt.getTime() - now.getTime() < 5 * 60 * 1000) {
    console.log("Token expired or expiring soon, refreshing...");
    // BUG 12 FIX: Match lead pipeline's refresh pattern (plain JSON POST, no Basic auth)
    const response = await fetch("https://sync.thewiseagent.com/WiseAuth/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        grant_type: "refresh_token",
        refresh_token: oauth.refresh_token
      })
    });

    if (!response.ok) {
      throw new Error(`Failed to refresh token: ${await response.text()}`);
    }

    const newTokens = await response.json();
    // BUG 12 FIX: Write back to f/switchboard/wiseagent_oauth (not f/wiseagent/credentials)
    await wmill.setResource({
      ...oauth,
      access_token: newTokens.access_token,
      refresh_token: newTokens.refresh_token || oauth.refresh_token,
      expires_at: newTokens.expires_at || ""
    }, "f/switchboard/wiseagent_oauth");

    return newTokens.access_token;
  }

  return oauth.access_token;
}

async function searchContactByEmail(accessToken: string, email: string): Promise<string | null> {
  const params = new URLSearchParams();
  params.append("requestType", "getContacts");
  params.append("email", email);

  const response = await fetch(`https://sync.thewiseagent.com/http/webconnect.asp?${params.toString()}`, {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${accessToken}`
    }
  });

  const result = await response.json();
  console.log("Search result:", JSON.stringify(result));

  // Check if contact was found - response format varies
  if (Array.isArray(result)) {
    const clientIdItem = result.find((item: any) => item.ClientID !== undefined);
    if (clientIdItem) {
      return clientIdItem.ClientID.toString();
    }
    // Check for contacts array
    const contactsItem = result.find((item: any) => item.contacts !== undefined);
    if (contactsItem?.contacts?.length > 0) {
      return contactsItem.contacts[0].ClientID?.toString() || null;
    }
  } else if (result.contacts && result.contacts.length > 0) {
    return result.contacts[0].ClientID?.toString() || null;
  } else if (result.ClientID) {
    return result.ClientID.toString();
  }

  return null;
}

async function addNoteToContact(accessToken: string, clientId: string, signerName: string, completedAt: string, templateName: string): Promise<boolean> {
  const noteDate = new Date(completedAt).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });

  const formData = new URLSearchParams();
  formData.append("requestType", "addContactNote");
  formData.append("clientids", clientId);
  formData.append("subject", `NDA Signed - ${templateName}`);
  formData.append("note", `${signerName} signed the ${templateName} agreement on ${noteDate}.`);
  formData.append("categories", "NDA Signed");

  const response = await fetch("https://sync.thewiseagent.com/http/webconnect.asp", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: formData.toString()
  });

  const result = await response.json();
  console.log("Add note result:", JSON.stringify(result));

  // Check for success
  if (Array.isArray(result)) {
    return result.some((item: any) => item.success === "true" || item.success === true);
  }
  return result.success === "true" || result.success === true;
}

async function addCategoryToContact(accessToken: string, clientId: string): Promise<boolean> {
  const formData = new URLSearchParams();
  formData.append("requestType", "updateContact");
  formData.append("clientID", clientId);
  formData.append("AddCategories", "NDA Signed");

  const response = await fetch("https://sync.thewiseagent.com/http/webconnect.asp", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: formData.toString()
  });

  const result = await response.json();
  console.log("Update category result:", JSON.stringify(result));
  return true;
}

async function createNewContact(accessToken: string, firstName: string, lastName: string, email: string): Promise<string | null> {
  const formData = new URLSearchParams();
  formData.append("requestType", "webcontact");
  formData.append("CFirst", firstName);
  formData.append("CLast", lastName);
  formData.append("CEmail", email);
  formData.append("Source", "DocuSeal NDA");
  formData.append("Categories", "NDA Signed");

  const response = await fetch("https://sync.thewiseagent.com/http/webconnect.asp", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: formData.toString()
  });

  const result = await response.json();
  console.log("Create contact result:", JSON.stringify(result));

  if (Array.isArray(result)) {
    const successItem = result.find((item: any) => item.success !== undefined);
    const clientIdItem = result.find((item: any) => item.ClientID !== undefined);
    if (successItem?.success === "true" || successItem?.success === true) {
      return clientIdItem?.ClientID?.toString() || null;
    }
  } else if (result.success === "true" || result.success === true) {
    return result.data?.ClientID?.toString() || result.ClientID?.toString() || null;
  }
  return null;
}

export async function main(body: DocuSealWebhook) {
  if (body.event_type !== "submission.completed") {
    return { status: "ignored", reason: `Event type ${body.event_type} not handled` };
  }

  const submitter = body.data.submitters[0];
  if (!submitter) {
    return { status: "error", reason: "No submitter found" };
  }

  const signerName = submitter.name;
  const signerEmail = submitter.email;
  const completedAt = submitter.completed_at;
  const templateName = body.data.template.name;
  const pdfUrl = submitter.documents?.[0]?.url || "No PDF";

  console.log(`NDA signed by ${signerName} (${signerEmail}) at ${completedAt}`);

  const nameParts = signerName.trim().split(/\s+/);
  const firstName = nameParts[0] || "";
  const lastName = nameParts.slice(1).join(" ") || "";

  let wiseAgentResult = {
    success: false,
    clientId: null as string | null,
    action: "none" as "created" | "updated" | "none",
    error: null as string | null
  };

  try {
    // BUG 12 FIX: Use f/switchboard/wiseagent_oauth (same as lead pipeline)
    const oauth = await wmill.getResource("f/switchboard/wiseagent_oauth") as WiseAgentOAuth;
    const accessToken = await refreshTokenIfNeeded(oauth);

    // Step 1: Check if contact already exists
    console.log(`Searching for existing contact with email: ${signerEmail}`);
    const existingClientId = await searchContactByEmail(accessToken, signerEmail);

    if (existingClientId) {
      // Contact exists - add note and update category
      console.log(`Found existing contact: ${existingClientId}. Adding NDA note...`);

      const noteAdded = await addNoteToContact(accessToken, existingClientId, signerName, completedAt, templateName);
      await addCategoryToContact(accessToken, existingClientId);

      wiseAgentResult = {
        success: true,
        clientId: existingClientId,
        action: "updated",
        error: null
      };
    } else {
      // Contact doesn't exist - create new
      console.log(`No existing contact found. Creating new contact...`);

      const newClientId = await createNewContact(accessToken, firstName, lastName, signerEmail);

      if (newClientId) {
        // Add the NDA signing note to the new contact too
        await addNoteToContact(accessToken, newClientId, signerName, completedAt, templateName);

        wiseAgentResult = {
          success: true,
          clientId: newClientId,
          action: "created",
          error: null
        };
      } else {
        wiseAgentResult = {
          success: false,
          clientId: null,
          action: "none",
          error: "Failed to create contact"
        };
      }
    }
  } catch (err) {
    console.error("Error with Wise Agent:", err);
    wiseAgentResult = {
      success: false,
      clientId: null,
      action: "none",
      error: err instanceof Error ? err.message : String(err)
    };
  }

  return {
    status: "success",
    signer: {
      name: signerName,
      firstName,
      lastName,
      email: signerEmail,
      completedAt
    },
    template: templateName,
    pdfUrl,
    wiseAgent: wiseAgentResult,
    message: `NDA completed by ${signerName} - Contact ${wiseAgentResult.action}`
  };
}
