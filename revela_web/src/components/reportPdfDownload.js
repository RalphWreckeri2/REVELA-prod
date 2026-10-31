export function reportPdfFilename(title, date = new Date()) {
  const safeTitle = String(title || "Report")
    .normalize("NFKD")
    .replace(/[<>:"/\\|?*]/g, "_")
    .split("")
    .filter(character => {
      const code = character.charCodeAt(0);
      return code >= 32 && code !== 127;
    })
    .join("")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  const dateStamp = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
  return `${safeTitle || "Report"}_${dateStamp}.pdf`;
}

export async function downloadCanvasAsPdf(
  canvas,
  {
    filename,
    orientation = "portrait",
    Pdf,
    createCanvas = () => document.createElement("canvas"),
  },
) {
  if (!canvas?.width || !canvas?.height) {
    throw new Error("The report image is empty.");
  }

  const PdfConstructor = Pdf ?? (await import("jspdf")).jsPDF;
  const pdf = new PdfConstructor({
    orientation,
    unit: "mm",
    format: "a4",
    compress: true,
  });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const sourcePageHeight = Math.floor(canvas.width * pageHeight / pageWidth);
  if (sourcePageHeight < 1) {
    throw new Error("The report image is too narrow to create a PDF.");
  }

  const pageCanvas = createCanvas();
  pageCanvas.width = canvas.width;
  const context = pageCanvas.getContext("2d");
  if (!context) throw new Error("Could not prepare the PDF page image.");

  let page = 0;
  for (let sourceY = 0; sourceY < canvas.height; sourceY += sourcePageHeight) {
    const sliceHeight = Math.min(sourcePageHeight, canvas.height - sourceY);
    pageCanvas.height = sliceHeight;
    context.drawImage(
      canvas,
      0,
      sourceY,
      canvas.width,
      sliceHeight,
      0,
      0,
      canvas.width,
      sliceHeight,
    );
    if (page > 0) pdf.addPage();
    const imageHeight = pageWidth * sliceHeight / canvas.width;
    pdf.addImage(
      pageCanvas.toDataURL("image/jpeg", 0.92),
      "JPEG",
      0,
      0,
      pageWidth,
      imageHeight,
      undefined,
      "FAST",
    );
    page += 1;
  }

  pdf.save(filename);
  return page;
}
