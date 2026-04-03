import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
);

export async function logError(
  functionName: string,
  errorMessage: string,
  context?: Record<string, unknown>
): Promise<string | null> {
  try {
    const { data, error } = await supabase.rpc("log_error", {
      p_function_name: functionName,
      p_error_message: errorMessage,
      p_context: context || {},
    });

    if (error) {
      console.error("Failed to log error to database:", error);
      return null;
    }

    return data;
  } catch (err) {
    console.error("Exception while logging error:", err);
    return null;
  }
}

export function withErrorLogging<T>(
  functionName: string,
  handler: () => Promise<T>
): Promise<T> {
  return handler().catch(async (error) => {
    const errorMessage = error instanceof Error ? error.message : String(error);
    await logError(functionName, errorMessage, {
      stack: error instanceof Error ? error.stack : undefined,
    });
    throw error;
  });
}