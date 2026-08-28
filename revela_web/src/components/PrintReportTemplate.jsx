import { useEffect } from "react";
import myLogo from "../assets/logo.png";
import sealImg from "../assets/seal.png";

/**
 * PrintReportTemplate Component
 *
 * A reusable wrapper designed for printing pages with official government branding layouts.
 * Automatically repeats headers and footers across pages using standard table-header-group structures.
 * 
 * Props:
 *   title          - main document header title
 *   subtitle       - description subtitle below the title (optional)
 *   date           - generation date string (optional)
 *   preparedBy     - preparer's name (optional)
 *   office         - LGU department name (optional, defaults to BPLO Mataasnakahoy)
 *   classification - confidentiality rank (optional, defaults to Official Use / Confidential)
 *   isLandscape    - orientation switch (optional, defaults to false)
 *   onClose        - callback run after the print preview is closed
 *   children       - target report tables or elements to print
 */
export default function PrintReportTemplate({
  title,
  subtitle,
  date,
  preparedBy,
  office = "BPLO Mataasnakahoy",
  classification = "Official Use / Confidential",
  isLandscape = false,
  onClose,
  children
}) {
  useEffect(() => {
    const handleAfterPrint = () => {
      if (onClose) onClose();
    };
    window.addEventListener("afterprint", handleAfterPrint);

    // Auto-trigger printing when template mounts
    const timer = setTimeout(() => {
      window.print();
    }, 500);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("afterprint", handleAfterPrint);
    };
  }, [onClose]);

  return (
    <div className="print-report-container hidden print:block bg-white text-black p-8 font-sans w-full min-h-screen">
      {/* Dynamic @page orientation rule */}
      <style>{`
        @media print {
          @page {
            size: ${isLandscape ? "landscape" : "portrait"};
            margin: 20mm 15mm 20mm 15mm;
          }
        }
      `}</style>

      <table className="w-full">
        {/* 1. Header component (Repeats on every page top) */}
        <thead>
          <tr>
            <td className="p-0">
              <div className="flex items-center justify-between w-full border-b-2 border-slate-900 pb-3 mb-6">
                {/* Left Side: Mataasnakahoy Seal */}
                <img src={sealImg} alt="Mataasnakahoy Seal" className="w-16 h-16 object-contain" />
                
                {/* Center Hierarchical letterhead */}
                <div className="text-center flex-1 mx-4">
                  <div className="text-[11px] uppercase tracking-wider text-gray-600 font-medium">Republic of the Philippines</div>
                  <div className="text-[11px] text-gray-600 font-medium">Province of Batangas</div>
                  <div className="text-[13px] font-bold text-gray-900 leading-normal mt-0.5">Municipality of Mataasnakahoy</div>
                  <div className="text-[13px] font-extrabold text-[#56ab2f] tracking-wide leading-normal mt-1 uppercase">OFFICE OF THE MUNICIPAL MAYOR</div>
                </div>
                
                {/* Right Side: Bagong Pilipinas Logo */}
                <img src={myLogo} alt="Bagong Pilipinas Logo" className="w-16 h-16 object-contain" />
              </div>
            </td>
          </tr>
        </thead>

        {/* 2. Main content flow (Title, Metadata, Tables, Signatures) */}
        <tbody>
          <tr>
            <td className="p-0">
              <div className="report-body">
                {/* Document Title */}
                <h2 className="text-lg font-bold text-center text-gray-900 mb-6 uppercase tracking-wide">
                  {title}
                </h2>
                
                {/* Document Description */}
                {subtitle && (
                  <p className="text-xs text-gray-500 italic text-center mb-6 -mt-4">
                    {subtitle}
                  </p>
                )}

                {/* Metadata Section */}
                <div className="grid grid-cols-2 gap-y-3 gap-x-6 bg-slate-50 border border-slate-200 rounded-lg p-4 mb-6 text-[11px]">
                  <div>
                    <span className="font-bold text-gray-500 mr-2">DATE GENERATED:</span>
                    <span className="text-gray-900 font-medium">{date || new Date().toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="font-bold text-gray-500 mr-2">OFFICE:</span>
                    <span className="text-gray-900 font-medium">{office}</span>
                  </div>
                  <div>
                    <span className="font-bold text-gray-500 mr-2">PREPARED BY:</span>
                    <span className="text-gray-900 font-medium">{preparedBy || "BPLO Staff"}</span>
                  </div>
                  <div>
                    <span className="font-bold text-gray-500 mr-2">CLASSIFICATION:</span>
                    <span className="text-gray-900 font-medium">{classification}</span>
                  </div>
                </div>

                {/* Main Content Area */}
                {children}

                {/* Signature block (Page break aware) */}
                <div className="mt-12 grid grid-cols-2 gap-8 text-[11px] page-break-before-avoid">
                  <div>
                    <div className="text-gray-500 font-bold mb-10">Prepared By:</div>
                    <div className="border-b border-slate-300 w-48 mb-1"></div>
                    <div className="font-bold text-gray-900">{(preparedBy || "BPLO Staff").toUpperCase()}</div>
                    <div className="text-gray-500 text-[10px]">REVELA System Operator</div>
                    <div className="text-gray-500 text-[10px]">Business Permits & Licensing Office</div>
                  </div>
                  <div>
                    <div className="text-gray-500 font-bold mb-10">Noted By:</div>
                    <div className="border-b border-slate-300 w-48 mb-1"></div>
                    <div className="font-bold text-gray-900">BPLO DEPARTMENT HEAD</div>
                    <div className="text-gray-500 text-[10px]">Business Permits & Licensing Office</div>
                  </div>
                </div>
              </div>
            </td>
          </tr>
        </tbody>

        {/* 3. Footer component (Repeats on every page bottom) */}
        <tfoot>
          <tr>
            <td className="p-0 pt-6">
              <div className="flex justify-between items-end border-t-2 border-slate-900 pt-3 w-full text-[10px] text-gray-500">
                {/* Left Column: Contact Info */}
                <div className="text-left space-y-0.5">
                  <div>Telephone #: <span className="font-semibold text-gray-700">461-2374</span></div>
                  <div>Email: <span className="font-semibold text-gray-700">licensingoffice2374@yahoo.com</span></div>
                </div>
                
                {/* Right Column: Slogans */}
                <div className="text-right flex flex-col items-end">
                  {/* HOPE slogan */}
                  <div className="flex items-center gap-0.5 text-[10px] font-bold text-gray-700">
                    <span className="flex items-baseline">
                      <span style={{ fontFamily: "cursive, 'Brush Script MT', sans-serif", fontSize: "16px", color: "#1e40af", fontWeight: "normal" }}>H</span>
                      <span>ealth</span>
                    </span>
                    <span className="text-gray-300 mx-0.5">|</span>
                    <span className="flex items-baseline">
                      <span style={{ fontFamily: "cursive, 'Brush Script MT', sans-serif", fontSize: "16px", color: "#1e40af", fontWeight: "normal" }}>O</span>
                      <span>pportunity</span>
                    </span>
                    <span className="text-gray-300 mx-0.5">|</span>
                    <span className="flex items-baseline">
                      <span style={{ fontFamily: "cursive, 'Brush Script MT', sans-serif", fontSize: "16px", color: "#1e40af", fontWeight: "normal" }}>P</span>
                      <span>eace & Order</span>
                    </span>
                    <span className="text-gray-300 mx-0.5">|</span>
                    <span className="flex items-baseline">
                      <span style={{ fontFamily: "cursive, 'Brush Script MT', sans-serif", fontSize: "16px", color: "#1e40af", fontWeight: "normal" }}>E</span>
                      <span>ducation & Economy</span>
                    </span>
                  </div>
                  
                  {/* LOVEMATAASNAKAHOY */}
                  <div className="text-[10px] font-extrabold mt-1 tracking-[0.25em] text-[#ed8936] uppercase">
                    LOVEMATAASNAKAHOY
                  </div>
                </div>
              </div>
              
              {/* System Audit Footer & Page Numbering */}
              <div className="text-[9px] text-gray-400 mt-2 flex justify-between items-center w-full">
                <span>REVELA System &bull; BPLO Compliance Audit Report</span>
                <span className="print-page-number font-medium"></span>
              </div>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
