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
