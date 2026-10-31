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
    headerCanvas,
    footerCanvas,
    pageGap = 12,
    pageBreaks = [],
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
  const headerHeight = headerCanvas ? pageWidth * headerCanvas.height / headerCanvas.width : 0;
  const footerHeight = footerCanvas ? pageWidth * footerCanvas.height / footerCanvas.width : 0;
  const contentTop = headerHeight ? headerHeight + pageGap : 0;
  const contentBottom = pageHeight - footerHeight - (footerHeight ? pageGap : 0);
  const contentHeight = contentBottom - contentTop;
  const sourcePageHeight = Math.floor(canvas.width * contentHeight / pageWidth);
  if (sourcePageHeight < 1) {
    throw new Error("The report image is too narrow to create a PDF.");
  }

  const pageCanvas = createCanvas();
  pageCanvas.width = canvas.width;
  const context = pageCanvas.getContext("2d");
  if (!context) throw new Error("Could not prepare the PDF page image.");

  let page = 0;
  for (let sourceY = 0; sourceY < canvas.height;) {
    const maxSourceY = Math.min(sourceY + sourcePageHeight, canvas.height);
    const safeBreak = pageBreaks
      .filter(position => position > sourceY && position <= maxSourceY)
      .sort((a, b) => b - a)[0];
    const sliceHeight = (safeBreak ?? maxSourceY) - sourceY;
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
    const bodyHeight = pageWidth * sliceHeight / canvas.width;
    pdf.addImage(
      pageCanvas.toDataURL("image/jpeg", 0.92),
      "JPEG",
      0,
      contentTop,
      pageWidth,
      bodyHeight,
      undefined,
      "FAST",
    );
    if (headerCanvas) {
      pdf.addImage(headerCanvas.toDataURL("image/jpeg", 0.92), "JPEG", 0, 0,
        pageWidth, headerHeight, undefined, "FAST");
    }
    if (footerCanvas) {
      pdf.addImage(footerCanvas.toDataURL("image/jpeg", 0.92), "JPEG", 0,
        pageHeight - footerHeight, pageWidth, footerHeight, undefined, "FAST");
    }
    page += 1;
    sourceY += sliceHeight;
  }

  pdf.save(filename);
  return page;
}
