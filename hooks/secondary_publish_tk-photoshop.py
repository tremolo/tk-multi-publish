# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import uuid
import tempfile
import photoshop

import tank
from tank import Hook
from tank import TankError

class PublishHook(Hook):
    """
    Single hook that implements publish functionality for secondary tasks
    """    
    def execute(self, tasks, work_template, comment, thumbnail_path, sg_task, primary_publish_path, progress_cb, **kwargs):
        """
        Main hook entry point
        :tasks:         List of secondary tasks to be published.  Each task is a 
                        dictionary containing the following keys:
                        {
                            item:   Dictionary
                                    This is the item returned by the scan hook 
                                    {   
                                        name:           String
                                        description:    String
                                        type:           String
                                        other_params:   Dictionary
                                    }
                                   
                            output: Dictionary
                                    This is the output as defined in the configuration - the 
                                    primary output will always be named 'primary' 
                                    {
                                        name:             String
                                        publish_template: template
                                        tank_type:        String
                                    }
                        }
                        
        :work_template: template
                        This is the template defined in the config that
                        represents the current work file
               
        :comment:       String
                        The comment provided for the publish
                        
        :thumbnail:     Path string
                        The default thumbnail provided for the publish
                        
        :sg_task:       Dictionary (shotgun entity description)
                        The shotgun task to use for the publish    
                        
        :primary_publish_path: Path string
                        This is the path of the primary published file as returned
                        by the primary publish hook
                        
        :progress_cb:   Function
                        A progress callback to log progress during pre-publish.  Call:
                        
                            progress_cb(percentage, msg)
                             
                        to report progress to the UI
        
        :returns:       A list of any tasks that had problems that need to be reported 
                        in the UI.  Each item in the list should be a dictionary containing 
                        the following keys:
                        {
                            task:   Dictionary
                                    This is the task that was passed into the hook and
                                    should not be modified
                                    {
                                        item:...
                                        output:...
                                    }
                                    
                            errors: List
                                    A list of error messages (strings) to report    
                        }
        """
        results = []
        
        # publish all tasks:
        for task in tasks:
            item = task["item"]
            output = task["output"]
            errors = []
        
            # report progress:
            progress_cb(0, "Publishing", task)
        
            if output["name"] == "send_to_review":
                review_errors = self.__send_to_review(primary_publish_path, sg_task, comment, progress_cb)
                if review_errors:
                    errors += review_errors
            else:
                # don't know how to publish this output types!
                errors.append("Don't know how to publish this item!")   

            # if there is anything to report then add to result
            if len(errors) > 0:
                # add result:
                results.append({"task":task, "errors":errors})
             
            progress_cb(100)
             
        return results


    def __send_to_review(self, primary_publish_path, sg_task, comment, progress_cb):
        """
        Create a version of the current document that can be uploaded as a
        Shotgun 'Version' entity and reviewed in Screening Room, etc. 
        """
        errors = []
        
        # Find the primary_publish entity:
        progress_cb(10, "Retrieving Primary Publish")
        found_publishes = tank.util.find_publish(self.parent.tank, 
                                                 [primary_publish_path],
                                                 fields=["id", "type", "code"])
        primary_publish = found_publishes.get(primary_publish_path)
        if not primary_publish:
            errors.append("Failed to find publish entity for %s" % primary_publish_path)
            return errors
        
        progress_cb(20, "Saving JPEG version of file")
        
        # set up the export options and get a file object:
        jpeg_path = os.path.join(tempfile.gettempdir(), "%s_sgtk.jpg" % uuid.uuid4().hex)
        jpeg_file = photoshop.RemoteObject('flash.filesystem::File', jpeg_path)
        jpeg_save_options = photoshop.RemoteObject('com.adobe.photoshop::JPEGSaveOptions')
        jpeg_save_options.quality = 12
        
        try:
            # save as a copy:
            photoshop.app.activeDocument.saveAs(jpeg_file, jpeg_save_options, True)        
            
            # construct the data needed to create a Shotgun 'Version' entity:
            ctx = self.parent.context
            data = {
                "user": ctx.user,
                "description": comment,
                "sg_first_frame": 1,
                "frame_count": 1,
                "frame_range": "1-1",
                "sg_last_frame": 1,
                "entity": ctx.entity,
                "sg_path_to_frames": primary_publish_path,
                "project": ctx.project,
                "sg_task": sg_task,
                "code": primary_publish["code"],
                "created_by": ctx.user
            }        
    
            if tank.util.get_published_file_entity_type(self.parent.tank) == "PublishedFile":
                data["published_files"] = [primary_publish]
            else:# == "TankPublishedFile"
                data["tank_published_file"] = primary_publish
    
            # create the version:        
            progress_cb(50.0, "Creating review Version...")
            version = self.parent.shotgun.create("Version", data)
    
            # upload jpeg
            progress_cb(70.0, "Uploading to Shotgun...")
            self.parent.shotgun.upload("Version", version['id'], jpeg_path, "sg_uploaded_movie" )
            
        finally:
            try:
                # attempt to clean up the jpeg:
                os.remove(jpeg_path)
            except:
                pass

        return errors

