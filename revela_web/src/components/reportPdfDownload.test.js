import assert from "node:assert/strict";
import test from "node:test";
import {
  downloadCanvasAsPdf,
  reportPdfFilename,
} from "./reportPdfDownload.js";

test("report PDF filenames are safe and use the local date", () => {
  const date = new Date(2026, 10, 1);
  assert.equal(
    reportPdfFilename('Profile: "Mataasnakahoy"/2026', date),
    "Profile_Mataasnakahoy_2026_2026-11-01.pdf",
  );
});

test("canvas PDF downloads are split into page-sized image slices", async () => {
  const pages = [];
  let savedFilename = null;
  class FakePdf {
    internal = { pageSize: { getWidth: () => 210, getHeight: () => 297 } };
    addPage() {
      pages.push({ page: true });
    }
    addImage(image, _format, _x, _y, _width, height) {
      pages.push({ image, height });
    }
    save(filename) {
      savedFilename = filename;
    }
  }
  const drawCalls = [];
  const createCanvas = () => ({
    width: 0,
    height: 0,
    getContext: () => ({
      drawImage: (...args) => drawCalls.push(args),
    }),
    toDataURL: () => `image-${drawCalls.length}`,
  });

  const pageCount = await downloadCanvasAsPdf(
    { width: 210, height: 600 },
    {
      filename: "report.pdf",
      Pdf: FakePdf,
      createCanvas,
    },
  );

  assert.equal(pageCount, 3);
  assert.equal(savedFilename, "report.pdf");
  assert.equal(drawCalls.length, 3);
  assert.deepEqual(drawCalls.map(call => call[4]), [297, 297, 6]);
});

test("PDF content reserves room for the official header and footer on every page", async () => {
  const operations = [];
  class FakePdf {
    internal = { pageSize: { getWidth: () => 210, getHeight: () => 297 } };
    addPage() {
      operations.push({ type: "page" });
    }
    addImage(image, _format, x, y, width, height) {
      operations.push({ type: image, x, y, width, height });
    }
    save() {}
  }
  const createCanvas = () => ({
    width: 0,
    height: 0,
    getContext: () => ({ drawImage: () => {} }),
    toDataURL: () => "body",
  });
  const namedCanvas = (name, width, height) => ({
    width,
    height,
    toDataURL: () => name,
  });

  const pageCount = await downloadCanvasAsPdf(namedCanvas("source", 210, 600), {
    filename: "report.pdf",
    Pdf: FakePdf,
    createCanvas,
    headerCanvas: namedCanvas("header", 210, 20),
    footerCanvas: namedCanvas("footer", 210, 10),
    pageBreaks: [240, 480],
  });

  assert.equal(pageCount, 3);
  const bodyPages = operations.filter(operation => operation.type === "body");
  assert.deepEqual(bodyPages.map(({ y, height }) => [y, height]), [[32, 240], [32, 240], [32, 120]]);
  assert.equal(operations.filter(operation => operation.type === "header").length, 3);
  assert.equal(operations.filter(operation => operation.type === "footer").length, 3);
  assert.ok(bodyPages.every(({ y, height }) => y + height <= 275));
});
