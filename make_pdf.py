from reportlab.pdfgen import canvas

def create_sample_pdf():
    c = canvas.Canvas("sample_approval.pdf")
    c.drawString(100, 750, "IT Service Desk Ticket: REQ-99214")
    c.drawString(100, 730, "Requestor: hiring.manager@company.com")
    c.drawString(100, 710, "Requested For: Evan Wright")
    c.drawString(100, 690, "Type: New Hire Onboarding - Developer Access")
    c.drawString(100, 670, "Date: 2023-07-28")
    c.drawString(100, 630, "Approval Status: APPROVED")
    c.drawString(100, 610, "Approved By: IT Director")
    c.save()

if __name__ == "__main__":
    create_sample_pdf()
