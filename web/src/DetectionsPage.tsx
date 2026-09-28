import { useState } from "react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./components/ui/table";
import { detectionLabel, outcome, sourceLabel, utcTime } from "./format";
import type { Detection } from "./types";

function Result({ detection }: { detection: Detection }) {
  const failed =
    detection.deletion !== "succeeded" ||
    detection.notification.startsWith("failed");
  return (
    <Badge variant={failed ? "destructive" : "secondary"}>
      {outcome(detection)}
    </Badge>
  );
}

export default function DetectionsPage({
  detections,
}: {
  detections: Detection[];
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = detections.find((item) => item.message_id === selectedId);

  return (
    <div className="content">
      <div className="page-heading heading-with-count">
        <div>
          <h1>Detections</h1>
          <p>Recent confirmed matches and recorded enforcement outcomes.</p>
        </div>
        <Badge variant="outline">{detections.length} shown</Badge>
      </div>
      {!detections.length ? (
        <Card size="sm">
          <CardContent className="empty-state">
            <strong>No detections recorded</strong>
            <p>
              Confirmed matches and their deletion outcomes will appear here.
              MediaGuard keeps metadata only.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card size="sm" className="history-card">
            <CardContent className="history-content">
              <div className="desktop-history">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User</TableHead>
                      <TableHead>Channel</TableHead>
                      <TableHead>Detection</TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead>Deleted at</TableHead>
                      <TableHead>Result</TableHead>
                      <TableHead>
                        <span className="sr-only">Details</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detections.map((item) => (
                      <TableRow
                        key={item.message_id}
                        data-state={
                          selectedId === item.message_id
                            ? "selected"
                            : undefined
                        }
                      >
                        <TableCell>
                          <div className="identity-cell">
                            <strong title={item.author_name ?? undefined}>
                              {item.author_name || "Unknown user"}
                            </strong>
                            <span>{item.author_id}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <span
                            className="table-name"
                            title={item.channel_name ?? undefined}
                          >
                            {item.channel_name
                              ? `#${item.channel_name}`
                              : item.channel_id}
                          </span>
                        </TableCell>
                        <TableCell>{detectionLabel(item)}</TableCell>
                        <TableCell>{sourceLabel(item.source)}</TableCell>
                        <TableCell className="timestamp-cell">
                          {utcTime(item.deleted_at)}
                        </TableCell>
                        <TableCell>
                          <Result detection={item} />
                        </TableCell>
                        <TableCell>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-label={`Details for message ${item.message_id}`}
                            onClick={() =>
                              setSelectedId(
                                selectedId === item.message_id
                                  ? null
                                  : item.message_id,
                              )
                            }
                          >
                            Details
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="mobile-history">
                {detections.map((item) => (
                  <div className="mobile-detection" key={item.message_id}>
                    <div className="mobile-detection-top">
                      <strong>{detectionLabel(item)}</strong>
                      <Result detection={item} />
                    </div>
                    <p className="mobile-identity">
                      {item.author_name || "Unknown user"}{" "}
                      <span>{item.author_id}</span>
                    </p>
                    <p>
                      {item.channel_name
                        ? `#${item.channel_name}`
                        : item.channel_id}{" "}
                      · {sourceLabel(item.source)}
                    </p>
                    <div className="mobile-detection-bottom">
                      <time>{utcTime(item.deleted_at)}</time>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setSelectedId(
                            selectedId === item.message_id
                              ? null
                              : item.message_id,
                          )
                        }
                      >
                        Details
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          {selected && (
            <Card size="sm" className="detail-card">
              <CardHeader className="detail-heading">
                <CardTitle>Detection detail</CardTitle>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedId(null)}
                >
                  Close
                </Button>
              </CardHeader>
              <CardContent>
                <dl className="detail-grid">
                  {selected.author_name && (
                    <div>
                      <dt>User</dt>
                      <dd>{selected.author_name}</dd>
                    </div>
                  )}
                  <div>
                    <dt>User ID</dt>
                    <dd>{selected.author_id}</dd>
                  </div>
                  {selected.guild_name && (
                    <div>
                      <dt>Server</dt>
                      <dd>{selected.guild_name}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Server ID</dt>
                    <dd>{selected.guild_id}</dd>
                  </div>
                  {selected.channel_name && (
                    <div>
                      <dt>Channel</dt>
                      <dd>#{selected.channel_name}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Channel ID</dt>
                    <dd>{selected.channel_id}</dd>
                  </div>
                  <div>
                    <dt>Original message ID</dt>
                    <dd>{selected.message_id}</dd>
                  </div>
                  {selected.original_filename && (
                    <div>
                      <dt>Filename</dt>
                      <dd>{selected.original_filename}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Detection</dt>
                    <dd>{detectionLabel(selected)}</dd>
                  </div>
                  {selected.detection_kind === "embed_phrase" && (
                    <>
                      <div>
                        <dt>Rule</dt>
                        <dd>{selected.rule_name || "Deleted rule"}</dd>
                      </div>
                      <div>
                        <dt>Rule ID</dt>
                        <dd>{selected.rule_id}</dd>
                      </div>
                    </>
                  )}
                  <div>
                    <dt>Source</dt>
                    <dd>{sourceLabel(selected.source)}</dd>
                  </div>
                  <div>
                    <dt>Detected at</dt>
                    <dd>{utcTime(selected.at)}</dd>
                  </div>
                  {selected.deleted_at && (
                    <div>
                      <dt>Deleted at</dt>
                      <dd>{utcTime(selected.deleted_at)}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Deletion</dt>
                    <dd>{selected.deletion.replaceAll("_", " ")}</dd>
                  </div>
                  <div>
                    <dt>Notification</dt>
                    <dd>{selected.notification.replaceAll("_", " ")}</dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
