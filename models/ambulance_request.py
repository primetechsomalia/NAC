from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import random
import logging

_logger = logging.getLogger(__name__)

class AmbulanceRequest(models.Model):
    _name = 'ambulance.request'
    _description = 'Codsiga Ambulance'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Add this line for chatter

    name = fields.Char(
        string='Request ID', required=True, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('ambulance.request'),
        track_visibility='onchange'  # Track changes on this field
    )
    patient_id = fields.Many2one('patient.management', string='Bukaan', required=True, track_visibility='onchange')
    pickup_location = fields.Many2one('location.management', string='Goob Qaadista', required=True, track_visibility='onchange')
    destination_location = fields.Many2one('location.management', string='Goobta Loo Wado', required=True, track_visibility='onchange')
    patient_condition = fields.Text(string='Sharaxaadda Xaaladda', track_visibility='onchange')
    request_time = fields.Datetime(string='Waqtiga Codsiga', default=fields.Datetime.now)
    completed_time = fields.Datetime(string='Waqtiga Dhameysashada')
    assigned_ambulance_id = fields.Many2one('ambulance.management', string='Ambulance-ka La Xiriray', track_visibility='onchange')
    status = fields.Selection([
        ('pending', 'Sugitaan'),
        ('in_progress', 'Dhex-socda'),
        ('completed', 'Dhameysay'),
        ('canceled', 'Laga Tirtiray')
    ], string='Xaaladda', default='pending', tracking=True)  # Enable tracking on the status field
    driver_id = fields.Many2one('staff.management', string='Darawalka La Xiriray', track_visibility='onchange')
    response_time = fields.Float(string='Waqtiga Jawaabta (daqiiqado)', compute='_compute_response_time', store=True)
    priority = fields.Selection([
        ('low', 'Hoose'),
        ('medium', 'Dhexdhexaad'),
        ('high', 'Sare'),
        ('critical', 'Qatar')
    ], string='Mudnaanta', compute='_compute_priority', store=True)
    eta = fields.Datetime(string='Waqtiga La Gaadhi Karo', compute='_compute_eta', store=True)

    @api.depends('patient_condition')
    def _compute_priority(self):
        for record in self:
            if record.patient_condition:
                condition = record.patient_condition.lower()
                if 'critical' in condition or 'severe' in condition:
                    record.priority = 'critical'
                elif 'urgent' in condition:
                    record.priority = 'high'
                elif 'moderate' in condition:
                    record.priority = 'medium'
                else:
                    record.priority = 'low'
            else:
                record.priority = 'low'

    @api.depends('request_time', 'completed_time')
    def _compute_response_time(self):
        for record in self:
            if record.status == 'completed' and record.completed_time:
                response_duration = (record.completed_time - record.request_time).total_seconds() / 60.0
                record.response_time = response_duration

    @api.depends('pickup_location', 'assigned_ambulance_id')
    def _compute_eta(self):
        for record in self:
            if record.pickup_location and record.assigned_ambulance_id and record.assigned_ambulance_id.current_location:
                distance = record.pickup_location.distance_to(record.assigned_ambulance_id.current_location)
                average_speed_kmh = 60 * (1 + random.uniform(-0.2, 0.2))  # Average speed with variation
                record.eta = fields.Datetime.add(record.request_time, timedelta(hours=distance / average_speed_kmh))
            else:
                record.eta = False

    def intelligent_assign_ambulance(self):
        """Automatically assign the nearest available ambulance to pending requests."""
        for request in self:
            if request.status == 'pending':
                available_ambulances = self.env['ambulance.management'].search([('status', '=', 'available')])
                nearest_ambulance = min(
                    available_ambulances,
                    key=lambda amb: amb.current_location.distance_to(request.pickup_location),
                    default=None
                )
                
                if nearest_ambulance:
                    request.assigned_ambulance_id = nearest_ambulance.id
                    request.status = 'in_progress'
                    nearest_ambulance.status = 'in_service'
                    nearest_ambulance.is_available = False
                    _logger.info(f"Assigned ambulance {nearest_ambulance.name} to request {request.name}.")
                    # Log the assignment in chatter
                    request.message_post(body=f"Assigned ambulance {nearest_ambulance.name} to the request.")
                else:
                    _logger.warning("All ambulances are busy. Cannot assign.")
                    raise UserError("Dhamaan Ambulance-yadu waa wada buuxan. Fadlan sug.")  # Use UserError

    @api.model
    def action_check_available_ambulances(self):
        """Check for available ambulances and assign to waiting requests."""
        # This function has been removed in this version as requested.
        _logger.info("No waiting list logic is currently implemented.")

    @api.model
    def _cron_dispatcher(self):
        """Scheduled action to process ambulance requests."""
        try:
            _logger.info("Starting the ambulance dispatcher.")

            # Check for available ambulances
            available_ambulances = self.env['ambulance.management'].search([('status', '=', 'available')])
            _logger.info(f"Found {len(available_ambulances)} available ambulances.")

            if available_ambulances:
                # Call the assignment functions only if there are available ambulances
                self.intelligent_assign_ambulance()
            else:
                _logger.info("No available ambulances found. Skipping assignment process.")

        except Exception as e:
            _logger.error(f"Error during ambulance assignment: {str(e)}")

    def action_set_pending(self):
        for record in self:
            record.status = 'pending'
            record.message_post(body="Status changed to 'pending'.")  # Log status change in chatter

    def action_set_in_progress(self):
        for record in self:
            record.status = 'in_progress'
            record.message_post(body="Status changed to 'in progress'.")  # Log status change in chatter

    def action_set_completed(self):
        for record in self:
            record.status = 'completed'
            record.completed_time = fields.Datetime.now()
            record.message_post(body="Request marked as completed.")  # Log completion in chatter
            
            # Make the assigned ambulance available
            if record.assigned_ambulance_id:
                record.assigned_ambulance_id.status = 'available'
                record.assigned_ambulance_id.is_available = True
                if record.driver_id:
                    record.driver_id.is_available = True
                _logger.info(f"Request {record.name} completed. Ambulance {record.assigned_ambulance_id.name} is now available.")

            # Check for in-progress requests without an assigned ambulance
            in_progress_requests = self.env['ambulance.request'].search([
                ('status', '=', 'pending'),
                ('assigned_ambulance_id', '=', False)  # Find requests that are in progress but have no ambulance assigned
            ])
            
            if in_progress_requests:
                for request in in_progress_requests:
                    _logger.info(f"Found in-progress request {request.name} with no assigned ambulance. Attempting to assign now.")
                    # Assign ambulance to this request
                    request.intelligent_assign_ambulance()  # This will try to assign available ambulances

                # Optionally, you can log the result of the assignment attempt
                _logger.info(f"Checked in-progress requests. Total found: {len(in_progress_requests)}.")
            else:
                _logger.info("No in-progress requests without assigned ambulances found.")

    def action_set_canceled(self):
        for record in self:
            record.status = 'canceled'
            record.message_post(body="Request has been canceled.")  # Log cancellation in chatter
