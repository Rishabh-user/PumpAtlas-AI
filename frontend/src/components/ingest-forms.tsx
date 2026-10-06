"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { SuccessNote } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { clientFetch } from "@/lib/api-client";

type Tab = "upload" | "urls" | "search";

export function IngestForms() {
  return (
    <Card>
      <Tabs defaultValue="upload">
        <div className="border-b border-border px-3 pt-1">
          <TabsList className="border-0">
            <TabsTrigger value="upload">Files</TabsTrigger>
            <TabsTrigger value="urls">URLs</TabsTrigger>
            <TabsTrigger value="search">Web search</TabsTrigger>
          </TabsList>
        </div>
        <CardContent>
          <TabsContent value="upload">
            <UploadForm />
          </TabsContent>
          <TabsContent value="urls">
            <UrlForm />
          </TabsContent>
          <TabsContent value="search">
            <WebSearchForm />
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );
}

function Feedback({
  message,
  tone,
}: {
  message: string | null;
  tone: "ok" | "error";
}) {
  if (!message) return null;
  if (tone === "ok") {
    return (
      <div className="mt-2">
        <SuccessNote>{message}</SuccessNote>
      </div>
    );
  }
  return (
    <p role="alert" className="mt-2 text-2xs text-destructive">
      {message}
    </p>
  );
}

function UploadForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // Multipart goes straight through the proxy so the boundary survives.
      const response = await fetch("/api/proxy/ingest/upload", {
        method: "POST",
        body: data,
        credentials: "include",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Upload failed");
      setResult(
        `${payload.accepted.length} file(s) ingested, ${payload.failures.length} failed. ` +
          `${payload.extraction_tasks.length} extraction job(s) queued.`,
      );
      form.reset();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="files">
          Datasheets, quotations, reference lists, spreadsheets
        </Label>
        <Input
          id="files"
          name="files"
          type="file"
          multiple
          required
          accept=".pdf,.docx,.doc,.xlsx,.xlsm,.csv,.html,.htm"
          className="mt-1 h-auto py-1.5 file:mr-3 file:rounded file:border-0 file:bg-primary/15 file:px-2 file:py-1 file:text-primary"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Input
          name="vendor_hint"
          placeholder="Vendor (if known)"
          className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
        <select
          name="confidence_level"
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          defaultValue="vendor_declared"
        >
          <option value="verified">Verified document</option>
          <option value="vendor_declared">Vendor declared</option>
          <option value="third_party">Third party</option>
        </select>
        <select
          name="document_kind"
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          defaultValue=""
        >
          <option value="">Detect document kind</option>
          <option value="datasheet">Datasheet</option>
          <option value="performance_curve">Performance curve</option>
          <option value="quotation">Quotation</option>
          <option value="certificate">Certificate</option>
          <option value="reference_list">Reference list</option>
          <option value="ga_drawing">GA drawing</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground/85">
          <Checkbox name="auto_extract" value="true" defaultChecked />
          Extract with AI on arrival
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground/85">
          <Checkbox name="auto_promote" value="true" />
          Auto-promote high-confidence extractions
        </label>
        <Button type="submit" disabled={busy} className="ml-auto">
          {busy ? "Uploading\u2026" : "Upload and ingest"}
        </Button>
      </div>
      <Feedback message={result} tone="ok" />
      <Feedback message={error} tone="error" />
    </form>
  );
}

function UrlForm() {
  const router = useRouter();
  const [urls, setUrls] = useState("");
  const [vendorHint, setVendorHint] = useState("");
  const [followDocs, setFollowDocs] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const list = urls
      .split(/[\s,]+/)
      .map((url) => url.trim())
      .filter(Boolean);
    if (!list.length) {
      setError("Add at least one URL");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload = await clientFetch<{ batch_id: string; queued: number }>(
        "/ingest/urls",
        {
          method: "POST",
          body: {
            urls: list,
            vendor_hint: vendorHint || null,
            auto_extract: true,
            follow_document_links: followDocs,
          },
        },
      );
      setResult(
        `${payload.queued} URL(s) queued in batch ${payload.batch_id.slice(0, 8)}.`,
      );
      setUrls("");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not queue the URLs",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="urls">
          Vendor pages or document URLs, one per line
        </Label>
        <Textarea
          id="urls"
          value={urls}
          onChange={(event) => setUrls(event.target.value)}
          rows={4}
          placeholder={
            "https://vendor.com/pumps/api-610-bb3\nhttps://vendor.com/datasheet.pdf"
          }
          className="mt-1 font-mono"
        />
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Input
          value={vendorHint}
          onChange={(event) => setVendorHint(event.target.value)}
          placeholder="Vendor (if known)"
          className="w-44"
        />
        <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground/85">
          <Checkbox
            checked={followDocs}
            onCheckedChange={(checked) => setFollowDocs(checked === true)}
          />
          Follow PDF and spreadsheet links found on each page
        </label>
        <Button type="submit" disabled={busy} className="ml-auto">
          {busy ? "Queueing\u2026" : "Queue for ingestion"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground/70">
        robots.txt is respected, and a page whose content has not changed since
        the last capture is skipped rather than duplicated.
      </p>
      <Feedback message={result} tone="ok" />
      <Feedback message={error} tone="error" />
    </form>
  );
}

function WebSearchForm() {
  const router = useRouter();
  const [recipe, setRecipe] = useState("vendor_discovery");
  const [pumpType, setPumpType] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [modelCode, setModelCode] = useState("");
  const [country, setCountry] = useState("");
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload = await clientFetch<{
        batch_id: string;
        objective: string;
      }>("/ingest/web-search", {
        method: "POST",
        body: {
          recipe: objective ? null : recipe,
          objective: objective || null,
          pump_type: pumpType || null,
          vendor_name: vendorName || null,
          model_code: modelCode || null,
          country: country ? country.toUpperCase() : null,
          max_results: 10,
          fetch_full_pages: true,
          auto_extract: true,
        },
      });
      setResult(`Search dispatched: ${payload.objective.slice(0, 120)}`);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not start the search",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <Label>Recipe</Label>
          <select
            value={recipe}
            onChange={(event) => setRecipe(event.target.value)}
            className="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            <option value="vendor_discovery">
              Find vendors for a pump type
            </option>
            <option value="vendor_intelligence">Research one vendor</option>
            <option value="pump_model">Find a model datasheet</option>
          </select>
        </label>
        {recipe === "vendor_discovery" ? (
          <>
            <Field
              label="Pump type"
              value={pumpType}
              onChange={setPumpType}
              placeholder="API 610 BB3 multistage"
            />
            <Field
              label="Country (ISO-2)"
              value={country}
              onChange={setCountry}
              placeholder="BR"
            />
          </>
        ) : null}
        {recipe !== "vendor_discovery" ? (
          <Field
            label="Vendor"
            value={vendorName}
            onChange={setVendorName}
            placeholder="Sulzer"
          />
        ) : null}
        {recipe === "pump_model" ? (
          <Field
            label="Model code"
            value={modelCode}
            onChange={setModelCode}
            placeholder="MSD 4x8x10"
          />
        ) : null}
      </div>

      <label className="block">
        <Label>Custom objective (overrides the recipe)</Label>
        <Input
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          placeholder="Find NORSOK M-501 coating specifications for offshore water injection pumps"
          className="mt-1"
        />
      </label>

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground/70">
          Parallel AI orchestrates the search; every hit is stored as a source
          before any extraction runs.
        </p>
        <Button type="submit" disabled={busy}>
          {busy ? "Dispatching\u2026" : "Run discovery"}
        </Button>
      </div>
      <Feedback message={result} tone="ok" />
      <Feedback message={error} tone="error" />
    </form>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <Label>{label}</Label>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="mt-1"
      />
    </label>
  );
}
